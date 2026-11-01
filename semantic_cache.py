"""Redis-backed semantic answer cache using Redis Search vector indexing."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import struct
import time
import uuid
from typing import Any, Optional, Sequence

try:
    import redis
    from redis.commands.search.field import TagField, TextField, VectorField
    from redis.commands.search.indexDefinition import IndexDefinition, IndexType
    from redis.exceptions import ResponseError
except ImportError:  # Keep the base chatbot usable before optional cache deps are installed.
    redis = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _safe_tag(value: str) -> str:
    """Escape Redis Search TAG separators and backslashes."""
    return re.sub(r"([\\,{}|])", r"\\\1", value)


class SemanticCache:
    """Store and retrieve scoped answer vectors in Redis Search."""

    def __init__(self) -> None:
        self.url = os.getenv("REDIS_URL", "").strip()
        self.enabled = os.getenv("SEMANTIC_CACHE_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
        self.threshold = float(os.getenv("SEMANTIC_CACHE_SIMILARITY_THRESHOLD", "0.90"))
        self.ttl_seconds = int(os.getenv("SEMANTIC_CACHE_TTL_SECONDS", "86400"))
        # New grounding policy: avoid serving answers cached under the older prompt rules.
        configured_scope = os.getenv("SEMANTIC_CACHE_SCOPE_ID", "local-default").strip()
        self.scope_id = f"{configured_scope}:evidence-v2"
        self.dimension = int(os.getenv("SEMANTIC_CACHE_EMBEDDING_DIMENSION", "384"))
        self.prefix = os.getenv("SEMANTIC_CACHE_KEY_PREFIX", "rag:semantic-cache:")
        self.index_name = os.getenv("SEMANTIC_CACHE_INDEX_NAME", "rag_semantic_cache_idx")
        self.connect_timeout = float(os.getenv("REDIS_CONNECT_TIMEOUT_SECONDS", "5"))
        self.socket_timeout = float(os.getenv("REDIS_SOCKET_TIMEOUT_SECONDS", "5"))
        self.client: Optional[Any] = None
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("SEMANTIC_CACHE_SIMILARITY_THRESHOLD must be between 0 and 1")
        if self.ttl_seconds <= 0:
            raise ValueError("SEMANTIC_CACHE_TTL_SECONDS must be positive")

    def start(self) -> bool:
        """Connect, verify Redis Search, and create the vector index if needed."""
        if not self.enabled or not self.url:
            logger.info("Semantic cache disabled or REDIS_URL not configured")
            return False
        if redis is None:
            logger.warning("Redis client package unavailable; continuing without semantic cache")
            return False
        try:
            self.client = redis.Redis.from_url(
                self.url,
                decode_responses=False,
                socket_connect_timeout=self.connect_timeout,
                socket_timeout=self.socket_timeout,
            )
            self.client.ping()
            try:
                self.client.ft(self.index_name).info()
            except ResponseError as exc:
                error_text = str(exc).lower()
                missing_index_errors = (
                    "unknown index name",
                    "search_index_not_found",
                    "index not found",
                )
                if not any(marker in error_text for marker in missing_index_errors):
                    raise
                self.client.ft(self.index_name).create_index(
                    [
                        TagField("scope_id"),
                        TagField("collection_id"),
                        TagField("fingerprint"),
                        TextField("question"),
                        VectorField("embedding", "FLAT", {
                            "TYPE": "FLOAT32", "DIM": self.dimension,
                            "DISTANCE_METRIC": "COSINE",
                        }),
                    ],
                    definition=IndexDefinition(prefix=[self.prefix], index_type=IndexType.HASH),
                )
            logger.info("Semantic cache connected to Redis Search")
            return True
        except Exception as exc:
            logger.warning("Semantic cache unavailable; continuing without cache: %s", exc)
            self.close()
            return False

    def close(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except RedisError:
                logger.debug("Error closing Redis connection", exc_info=True)
            self.client = None

    @staticmethod
    def collection_id(sources: Sequence[str]) -> str:
        normalized = "\n".join(sorted({source.strip() for source in sources if source.strip()}))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def collection_fingerprint(records: Sequence[tuple[str, str, Any]]) -> str:
        digest = hashlib.sha256()
        for source, content, metadata in sorted(records, key=lambda row: (row[0], str(row[2]), row[1])):
            digest.update(source.encode("utf-8", errors="replace"))
            digest.update(b"\0")
            digest.update(str(metadata).encode("utf-8", errors="replace"))
            digest.update(b"\0")
            digest.update(content.encode("utf-8", errors="replace"))
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def is_cacheable_question(question: str) -> bool:
        """Conservatively reject conversational follow-ups without history context."""
        text = question.strip().lower()
        if len(text) < 8 or len(text.split()) < 3:
            return False
        if re.search(r"\b(it|this|that|these|those|they|them|he|she|her|his|former|latter)\b", text):
            return False
        return not bool(re.match(
            r"^(and|also|what about|how about|why|which one|who is he|who is she|"
            r"what does that|what do they|tell me more|elaborate|continue|there|that|it)\b",
            text,
        ))

    @staticmethod
    def is_cacheable_answer(answer: str) -> bool:
        """Do not retain empty, error-like, or model refusal responses."""
        text = answer.strip().lower()
        if not text or len(text) < 3:
            return False
        excluded = (
            "query failed:", "indexing failed:", "internal server error",
            "i cannot assist with that request", "i can't assist with that request",
            "i cannot help with that request", "i'm unable to help with that request",
        )
        return not any(marker in text for marker in excluded)

    def lookup(self, question: str, embedding: Sequence[float], collection_id: str,
               fingerprint: str) -> Optional[dict[str, Any]]:
        if self.client is None:
            return None
        try:
            vector = [float(value) for value in embedding]
            if len(vector) != self.dimension:
                logger.warning("Skipping semantic cache lookup: expected %d dimensions, got %d", self.dimension, len(vector))
                return None
            query = (
                f"(@scope_id:{{{_safe_tag(self.scope_id)}}}) "
                f"(@collection_id:{{{_safe_tag(collection_id)}}}) "
                f"(@fingerprint:{{{_safe_tag(fingerprint)}}})"
                f"=>[KNN 1 @embedding $vec AS distance]"
            )
            result = self.client.ft(self.index_name).search(
                query, query_params={"vec": struct.pack(f"{len(vector)}f", *vector)},
                sort_by="distance", return_fields=["answer", "sources", "distance", "hit_count"], dialect=2,
            )
            if not result.docs:
                return None
            item = result.docs[0]
            similarity = 1.0 - float(item.distance)
            if similarity < self.threshold:
                return None
            key = item.id
            pipe = self.client.pipeline()
            pipe.hincrby(key, "hit_count", 1)
            pipe.execute()
            answer = item.answer.decode("utf-8") if isinstance(item.answer, bytes) else item.answer
            source_data = item.sources.decode("utf-8") if isinstance(item.sources, bytes) else item.sources
            return {"answer": answer, "sources": json.loads(source_data), "_cache_similarity": similarity}
        except Exception as exc:
            logger.warning("Semantic cache lookup failed; treating as miss: %s", exc)
            return None

    def store(self, question: str, embedding: Sequence[float], answer: str,
              sources: list[dict[str, Any]], collection_id: str, fingerprint: str) -> None:
        if self.client is None:
            return
        try:
            vector = [float(value) for value in embedding]
            if len(vector) != self.dimension or not answer.strip():
                return
            key = f"{self.prefix}{uuid.uuid4().hex}"
            fields = {
                "question": question,
                "embedding": struct.pack(f"{len(vector)}f", *vector),
                "answer": answer,
                "sources": json.dumps(sources, ensure_ascii=False),
                "collection_id": collection_id,
                "fingerprint": fingerprint,
                "scope_id": self.scope_id,
                "created_at": str(int(time.time())),
                "hit_count": "0",
            }
            self.client.hset(key, mapping=fields)
            self.client.expire(key, self.ttl_seconds)
        except Exception as exc:
            logger.warning("Semantic cache write failed; returning generated answer: %s", exc)

    def invalidate_collection(self, collection_id: str) -> None:
        """Delete cached entries for a collection after its indexed content changes."""
        if self.client is None:
            return
        try:
            cursor = 0
            while True:
                cursor, keys = self.client.scan(cursor=cursor, match=f"{self.prefix}*", count=500)
                for key in keys:
                    data = self.client.hmget(key, "scope_id", "collection_id")
                    scope = data[0].decode() if data[0] else ""
                    coll = data[1].decode() if data[1] else ""
                    if scope == self.scope_id and coll == collection_id:
                        self.client.delete(key)
                if cursor == 0:
                    break
        except Exception as exc:
            logger.warning("Semantic cache invalidation failed: %s", exc)

    def invalidate_all(self) -> None:
        """Clear this cache namespace after any successful document upload."""
        if self.client is None:
            return
        try:
            cursor = 0
            while True:
                cursor, keys = self.client.scan(cursor=cursor, match=f"{self.prefix}*", count=500)
                if keys:
                    self.client.delete(*keys)
                if cursor == 0:
                    break
        except Exception as exc:
            logger.warning("Semantic cache invalidation failed: %s", exc)
