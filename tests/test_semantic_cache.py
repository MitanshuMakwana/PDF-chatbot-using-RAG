"""Deterministic semantic-cache tests; live Redis Search tests are opt-in."""

from __future__ import annotations

import math
import os
import re
import struct
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from semantic_cache import SemanticCache, redis


class FakeSearch:
    def __init__(self, client):
        self.client = client
        self.created_fields = None

    def info(self):
        if not self.client.index_created:
            from redis.exceptions import ResponseError
            raise ResponseError("SEARCH_INDEX_NOT_FOUND Index not found: rag_semantic_cache_idx")
        return {}

    def create_index(self, fields, definition):
        self.client.index_created = True
        self.created_fields = fields

    def search(self, query, query_params, **kwargs):
        tags = {name: value for name, value in re.findall(r"@([a-z_]+):\{([^}]+)\}", query)}
        query_vec = struct.unpack("2f", query_params["vec"])
        candidates = []
        for key, record in list(self.client.records.items()):
            if record["expires"] <= time.monotonic():
                del self.client.records[key]
                continue
            if any(record["fields"].get(name) != val for name, val in tags.items()):
                continue
            vec = struct.unpack("2f", record["fields"]["embedding"])
            denom = math.sqrt(sum(x*x for x in vec) * sum(x*x for x in query_vec))
            distance = 1 - sum(x*y for x, y in zip(vec, query_vec)) / denom
            candidates.append((distance, key, record["fields"]))
        candidates.sort()
        docs = []
        for distance, key, fields in candidates[:1]:
            docs.append(SimpleNamespace(
                id=key, answer=fields["answer"].encode(), sources=fields["sources"].encode(),
                distance=str(distance).encode(), hit_count=fields["hit_count"].encode(),
            ))
        return SimpleNamespace(docs=docs)


class FakePipeline:
    def __init__(self, client): self.client = client; self.actions = []
    def hincrby(self, key, field, amount): self.actions.append((key, field, amount)); return self
    def execute(self):
        for key, field, amount in self.actions:
            self.client.records[key]["fields"][field] = str(int(self.client.records[key]["fields"][field]) + amount)


class FakeRedis:
    def __init__(self): self.records = {}; self.index_created = True; self.search = FakeSearch(self)
    def ft(self, name): return self.search
    def pipeline(self): return FakePipeline(self)
    def hset(self, key, mapping): self.records[key] = {"fields": mapping, "expires": float("inf")}
    def expire(self, key, ttl): self.records[key]["expires"] = time.monotonic() + ttl
    def hmget(self, key, *fields):
        record = self.records.get(key, {}).get("fields", {})
        return [record.get(field) for field in fields]
    def scan(self, cursor=0, match=None, count=500): return 0, list(self.records)
    def delete(self, *keys):
        for key in keys: self.records.pop(key, None)
    def ping(self): return True
    def close(self): pass


def make_cache(*, threshold="0.9", ttl="60", scope="test-tenant"):
    with patch.dict(os.environ, {
        "SEMANTIC_CACHE_SIMILARITY_THRESHOLD": threshold,
        "SEMANTIC_CACHE_TTL_SECONDS": ttl,
        "SEMANTIC_CACHE_SCOPE_ID": scope,
        "SEMANTIC_CACHE_EMBEDDING_DIMENSION": "2",
    }, clear=False):
        cache = SemanticCache()
    cache.client = FakeRedis()
    return cache


class SemanticCacheUnitTests(unittest.TestCase):
    def setUp(self):
        self.cache = make_cache()
        self.collection = self.cache.collection_id(["handbook.pdf"])
        self.fingerprint = self.cache.collection_fingerprint([("handbook.pdf", "indexed text", {"page": 1})])

    def test_first_question_misses_then_persists_and_hits(self):
        vector = [1.0, 0.0]
        self.assertIsNone(self.cache.lookup("What is the policy?", vector, self.collection, self.fingerprint))
        self.cache.store("What is the policy?", vector, "Policy answer", [{"source": "handbook.pdf", "pages": [1]}], self.collection, self.fingerprint)
        hit = self.cache.lookup("What is the policy?", vector, self.collection, self.fingerprint)
        self.assertEqual(hit["answer"], "Policy answer")
        self.assertEqual(hit["sources"][0]["source"], "handbook.pdf")
        entry = next(iter(self.cache.client.records.values()))["fields"]
        self.assertEqual(entry["question"], "What is the policy?")
        self.assertEqual(entry["hit_count"], "1")
        self.assertEqual(len(entry["embedding"]), 8)

    def test_similar_and_unrelated_vectors_obey_threshold(self):
        self.cache.store("What is the policy?", [1.0, 0.0], "Answer", [], self.collection, self.fingerprint)
        self.assertIsNotNone(self.cache.lookup("Explain the policy", [0.995, 0.1], self.collection, self.fingerprint))
        self.assertIsNone(self.cache.lookup("Unrelated query", [0.0, 1.0], self.collection, self.fingerprint))

    def test_collection_fingerprint_and_tenant_isolation(self):
        self.cache.store("question", [1.0, 0.0], "Private answer", [], self.collection, self.fingerprint)
        self.assertIsNone(self.cache.lookup("question", [1.0, 0.0], "other-collection", self.fingerprint))
        self.assertIsNone(self.cache.lookup("question", [1.0, 0.0], self.collection, "new-fingerprint"))
        other_tenant = make_cache(scope="different-tenant")
        other_tenant.client = self.cache.client
        self.assertIsNone(other_tenant.lookup("question", [1.0, 0.0], self.collection, self.fingerprint))

    def test_user_scope_changes_cache_identity_and_invalidation_is_scoped(self):
        alice = self.cache.scope_for_user("alice-id")
        bob = self.cache.scope_for_user("bob-id")
        self.assertNotEqual(alice, bob)
        alice_collection = self.cache.collection_id(["handbook.pdf"], scope_id=alice)
        bob_collection = self.cache.collection_id(["handbook.pdf"], scope_id=bob)
        self.assertNotEqual(alice_collection, bob_collection)
        self.cache.store("question", [1.0, 0.0], "Alice answer", [], alice_collection, self.fingerprint, scope_id=alice)
        self.cache.store("question", [1.0, 0.0], "Bob answer", [], bob_collection, self.fingerprint, scope_id=bob)
        self.cache.invalidate_scope(alice)
        self.assertEqual(len(self.cache.client.records), 1)
        only_entry = next(iter(self.cache.client.records.values()))["fields"]
        self.assertEqual(only_entry["scope_id"], bob)

    def test_expired_entries_are_not_returned(self):
        cache = make_cache(ttl="1")
        coll = cache.collection_id(["a.pdf"])
        fp = cache.collection_fingerprint([("a.pdf", "text", {})])
        cache.store("A complete question", [1.0, 0.0], "Answer", [], coll, fp)
        time.sleep(1.05)
        self.assertIsNone(cache.lookup("A complete question", [1.0, 0.0], coll, fp))

    def test_upload_invalidation_clears_entries(self):
        self.cache.store("question", [1.0, 0.0], "answer", [], self.collection, self.fingerprint)
        self.cache.invalidate_all()
        self.assertEqual(self.cache.client.records, {})

    def test_context_dependent_questions_and_unsafe_answers_are_not_cacheable(self):
        self.assertFalse(SemanticCache.is_cacheable_question("What about that one?"))
        self.assertFalse(SemanticCache.is_cacheable_question("Can you explain it more?"))
        self.assertTrue(SemanticCache.is_cacheable_question("Summarize the employee leave policy"))
        self.assertFalse(SemanticCache.is_cacheable_answer("I cannot assist with that request."))
        self.assertFalse(SemanticCache.is_cacheable_answer("   "))

    def test_wrong_vector_dimension_is_a_safe_miss_and_not_stored(self):
        self.assertIsNone(self.cache.lookup("question", [1.0], self.collection, self.fingerprint))
        self.cache.store("question", [1.0], "answer", [], self.collection, self.fingerprint)
        self.assertFalse(self.cache.client.records)

    def test_invalid_threshold_is_rejected(self):
        with self.assertRaises(ValueError):
            make_cache(threshold="1.1")

    def test_redis_client_missing_keeps_cache_disabled(self):
        cache = make_cache()
        with patch("semantic_cache.redis", None):
            cache.url = "redis://127.0.0.1:6379/0"
            cache.client = None
            self.assertFalse(cache.start())
            self.assertIsNone(cache.client)

    def test_start_creates_384_dimension_cosine_index_for_hosted_url(self):
        if redis is None:
            self.skipTest("redis-py is not installed")
        cache = make_cache()
        fake_client = FakeRedis()
        fake_client.index_created = False
        cache.url = "rediss://default:secret@example.invalid:12345/0"
        cache.dimension = 384
        with patch("semantic_cache.redis.Redis.from_url", return_value=fake_client):
            self.assertTrue(cache.start())
        vector_field = next(field for field in fake_client.search.created_fields if field.__class__.__name__ == "VectorField")
        self.assertEqual(vector_field.name, "embedding")
        self.assertEqual(vector_field.args[6], 384)
        self.assertEqual(vector_field.args[8], "COSINE")


@unittest.skipUnless(
    os.getenv("RUN_REDIS_INTEGRATION") == "1" and os.getenv("REDIS_URL") and redis is not None,
    "Set RUN_REDIS_INTEGRATION=1 and REDIS_URL to run live Redis Search checks",
)
class RedisSearchIntegrationTests(unittest.TestCase):
    def test_connection_and_vector_index_configuration(self):
        cache = SemanticCache()
        try:
            self.assertTrue(cache.start(), "Redis Search must be reachable and support vector indexing")
            info = cache.client.ft(cache.index_name).info()
            attributes = info.get("attributes", [])
            normalized_fields = []
            def text(value):
                return value.decode() if isinstance(value, bytes) else value

            for field in attributes:
                if isinstance(field, dict):
                    normalized_fields.append({
                        text(key): text(value)
                        for key, value in field.items()
                    })
                    continue
                # Redis Search FT.INFO returns each schema attribute as a flat
                # alternating list of key/value pairs on redis-py 5.x.
                if isinstance(field, (list, tuple)):
                    pairs = {}
                    for index in range(0, len(field) - 1, 2):
                        pairs[text(field[index])] = text(field[index + 1])
                    normalized_fields.append(pairs)
            embedding = [field for field in normalized_fields if field.get("attribute") == "embedding"]
            self.assertTrue(embedding, "Expected embedding vector field in Redis Search index")
            vector_field = embedding[0]
            self.assertEqual(str(vector_field.get("type", "")).upper(), "VECTOR")
            self.assertEqual(int(vector_field["dim"]), 384)
            self.assertEqual(str(vector_field["distance_metric"]).upper(), "COSINE")
        finally:
            cache.close()


if __name__ == "__main__":
    unittest.main()
