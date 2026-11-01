import os
import random
import re
import sys
import time
import logging
from typing import Any, Optional, Sequence

from dotenv import load_dotenv
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.messages import SystemMessage, HumanMessage
from semantic_cache import SemanticCache

load_dotenv()

# Windows consoles often use cp1252 and crash on PDF symbols like \uf0b7
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Retry settings for Gemini free-tier 429 / RESOURCE_EXHAUSTED
LLM_MAX_RETRIES = 5
LLM_BASE_DELAY_SEC = 2.0
logger = logging.getLogger(__name__)


def sanitize_text(text: str) -> str:
    """Normalize PDF/Word oddities that break Windows encoding or confuse the LLM."""
    if not text:
        return ""

    replacements = {
        "\uf0b7": "-",  # Word/PDF private-use bullet
        "\uf0a7": "-",
        "\u2022": "-",
        "\u2023": "-",
        "\u25cf": "-",
        "\u25e6": "-",
        "\u00a0": " ",
        "\u200b": "",
        "\ufeff": "",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
    }

    for bad, good in replacements.items():
        text = text.replace(bad, good)

    text = text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    text = re.sub(r"[\uE000-\uF8FF]", "-", text)
    return text


def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        print(*(sanitize_text(str(arg)) for arg in args), **kwargs)


def format_answer(text: str) -> str:
    if not text:
        return text

    text = sanitize_text(text).strip()
    text = re.sub(r"([^\n])\s*(\*\*[^*\n]+:\*\*)", r"\1\n\n\2", text)
    text = re.sub(r"(\*\*[^*\n]+\*\*)\s*-\s+", r"\1\n\n- ", text)
    text = re.sub(r"(?<!\n)\s+-\s+(?=[A-Za-z0-9])", "\n- ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in ("429", "resource_exhausted", "rate limit", "quota", "too many requests")
    )


def invoke_llm_with_backoff(llm, messages):
    """Retry Gemini calls with exponential backoff on 429 / quota errors."""
    last_error = None

    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            return llm.invoke(messages)
        except Exception as exc:
            last_error = exc
            if not is_rate_limit_error(exc) or attempt >= LLM_MAX_RETRIES:
                raise

            delay = LLM_BASE_DELAY_SEC * (2 ** attempt) + random.uniform(0, 1)
            safe_print(
                f"Rate limit hit — retrying in {delay:.1f}s "
                f"(attempt {attempt + 1}/{LLM_MAX_RETRIES})"
            )
            time.sleep(delay)

    raise last_error


class RAGAssistant:
    def __init__(self, persist_dir):
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )

        self.db = Chroma(
            persist_directory=persist_dir,
            embedding_function=self.embeddings,
        )

        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.4,
            top_p=0.9,
            max_retries=0,  # we handle retries with explicit exponential backoff
        )
        self.semantic_cache: Optional[SemanticCache] = None

    def add_document(self, filepath, filename):
        loader = PyMuPDFLoader(filepath)
        documents = loader.load()

        for document in documents:
            document.page_content = sanitize_text(document.page_content)

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1200,
            chunk_overlap=300,
            separators=["\n\n", "\n", ".", " ", ""],
        )

        chunks = splitter.split_documents(documents)

        for chunk in chunks:
            chunk.page_content = sanitize_text(chunk.page_content)
            chunk.metadata["source"] = filename

            if "page" in chunk.metadata:
                chunk.metadata["page"] += 1

            page_num = chunk.metadata.get("page", "N/A")
            chunk.page_content = (
                f"[Document: {filename} | Page: {page_num}]\n"
                + chunk.page_content
            )

        self.db.add_documents(chunks)
        if self.semantic_cache is not None:
            self.semantic_cache.invalidate_all()
        return len(chunks)

    def list_documents(self):
        try:
            data = self.db.get()
            sources = set()
            for meta in data["metadatas"]:
                if meta and "source" in meta:
                    sources.add(meta["source"])
            return sorted(list(sources))
        except Exception:
            return []

    def query(self, question, filter_sources=None):
        active_sources = sorted(set(filter_sources or []))
        cache = self.semantic_cache
        cache_embedding = None
        collection_id = fingerprint = None
        cache_allowed = bool(
            cache is not None and cache.client is not None and active_sources
            and cache.is_cacheable_question(question)
        )
        if cache_allowed:
            try:
                # One embedding is reused by Redis and Chroma on a miss.
                cache_embedding = self.embeddings.embed_query(question)
                collection_id = cache.collection_id(active_sources)
                data = self.db.get(include=["documents", "metadatas"])
                records = [
                    (meta.get("source", ""), content, meta)
                    for content, meta in zip(data.get("documents") or [], data.get("metadatas") or [])
                    if meta and meta.get("source") in active_sources
                ]
                fingerprint = cache.collection_fingerprint(records)
                cached = cache.lookup(question, cache_embedding, collection_id, fingerprint)
                if cached is not None:
                    cached.pop("_cache_similarity", None)
                    logger.info("Semantic cache hit")
                    return cached
                logger.info("Semantic cache miss")
            except Exception as exc:
                # Cache preparation is optional; never make it block normal RAG.
                logger.warning("Semantic cache preparation failed; continuing with RAG: %s", exc)
                cache_embedding = None

        docs_scores = self._retrieve(question, filter_sources, cache_embedding)

        for doc, score in docs_scores:
            safe_print(
                f"score={score:.3f} | "
                f"source={doc.metadata.get('source')} | "
                f"{sanitize_text(doc.page_content[:80])}"
            )

        docs = [doc for doc, _score in docs_scores]

        if not docs:
            return {
                "answer": "No relevant documents found.",
                "sources": [],
            }

        for i, doc in enumerate(docs, 1):
            safe_print("\n" + "=" * 60)
            safe_print(f"Chunk {i}")
            safe_print(f"Source: {doc.metadata.get('source')}")
            safe_print(f"Page: {doc.metadata.get('page')}")
            safe_print(sanitize_text(doc.page_content[:500]))

        active_sources = list(dict.fromkeys(
            doc.metadata.get("source", "Unknown") for doc in docs
        ))
        multi_doc = len(filter_sources or active_sources) > 1

        context_blocks = []
        for i, doc in enumerate(docs, start=1):
            source_name = doc.metadata.get("source", "Unknown")
            page_num = doc.metadata.get("page", "N/A")
            content = sanitize_text(doc.page_content)
            context_blocks.append(
                f"[Excerpt {i} | Document: {source_name} | Page: {page_num}]\n{content}"
            )

        context = "\n\n---\n\n".join(context_blocks)

        if multi_doc:
            doc_list = ", ".join(filter_sources or active_sources)
            multi_doc_rules = f"""
MULTI-DOCUMENT MODE:
You have context from multiple uploaded documents: {doc_list}.

- Use information from ALL relevant documents when the question needs a combined view.
- If the user asks about one specific document, answer from that document only.
- If the user asks to compare or combine, clearly cover each document and then synthesize.
- When distinguishing documents, you MAY mention their file names.
- Do not ignore an uploaded document if the context contains useful information from it.
"""
        else:
            multi_doc_rules = """
SINGLE-DOCUMENT MODE:
- Never mention documents, sources, context, excerpts, page numbers, or file names.
"""

        system_prompt = f"""You are a helpful assistant that answers questions about uploaded documents such as resumes, reports, and manuals.

CORE RULES:
- Use ONLY the provided context. Never invent or assume information.
- Match your tone and structure to what the user actually asked.
- Write like a knowledgeable human, not a form or database dump.
{multi_doc_rules}
HOW TO TAILOR RESPONSES:

1. Identity / people questions: answer with names and roles clearly.
2. Enrollment / ID / guide / department questions: list each fact plainly.
3. Skill questions: group under short headings with one bullet per item.
4. Comparison / multi-document questions: cover each document, then synthesize.
5. Short factual questions: 1-2 direct sentences.

FORMATTING RULES:
- Use markdown with blank lines between sections.
- Use "-" for bullet lists.
- Use **bold** only for short labels.
- If information is missing, say so briefly. Do not guess."""

        human_prompt = f"""Context:
{context}

Question:
{question}

Answer in a natural, tailored way following the rules above:"""

        response = invoke_llm_with_backoff(
            self.llm,
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt),
            ],
        )

        unique_sources = {}
        for doc in docs:
            src = doc.metadata.get("source", "Unknown")
            page = doc.metadata.get("page", None)
            if src not in unique_sources:
                unique_sources[src] = set()
            if page is not None:
                unique_sources[src].add(page)

        sources_summary = [
            {
                "source": src,
                "pages": sorted(list(pages)) if pages else "N/A",
            }
            for src, pages in unique_sources.items()
        ]

        result = {
            "answer": format_answer(response.content),
            "sources": sources_summary,
        }
        if (
            cache_allowed and cache_embedding is not None and collection_id and fingerprint
            and isinstance(result["answer"], str) and cache.is_cacheable_answer(result["answer"])
            and docs and "no relevant documents found" not in result["answer"].lower()
        ):
            cache.store(
                question, cache_embedding, result["answer"], result["sources"],
                collection_id, fingerprint,
            )
        return result

    def _retrieve(self, question, filter_sources=None, query_embedding: Optional[Sequence[float]] = None):
        """
        Retrieve chunks with per-document coverage so one PDF cannot crowd out others.
        """
        search = self.db.similarity_search_by_vector_with_relevance_scores if query_embedding is not None else self.db.similarity_search_with_relevance_scores
        if not filter_sources:
            if query_embedding is not None:
                return search(query_embedding, k=6)
            return self.db.similarity_search_with_relevance_scores(question, k=6)

        if len(filter_sources) == 1:
            if query_embedding is not None:
                return search(query_embedding, k=6, filter={"source": filter_sources[0]})
            return self.db.similarity_search_with_relevance_scores(question, k=6, filter={"source": filter_sources[0]})

        per_doc_k = 4
        min_per_doc = 2
        max_total = per_doc_k * len(filter_sources)

        by_source = {}
        for source in filter_sources:
            if query_embedding is not None:
                by_source[source] = search(query_embedding, k=per_doc_k, filter={"source": source})
            else:
                by_source[source] = self.db.similarity_search_with_relevance_scores(question, k=per_doc_k, filter={"source": source})

        merged = []
        seen = set()

        def add_chunk(doc, score):
            key = (
                doc.metadata.get("source"),
                doc.metadata.get("page"),
                doc.page_content[:120],
            )
            if key in seen:
                return False
            seen.add(key)
            merged.append((doc, score))
            return True

        # Guarantee minimum chunks from every active document first
        for source in filter_sources:
            for doc, score in by_source[source][:min_per_doc]:
                add_chunk(doc, score)

        # Fill remaining slots with highest-scoring leftovers across all docs
        leftovers = []
        for source in filter_sources:
            for doc, score in by_source[source][min_per_doc:]:
                key = (
                    doc.metadata.get("source"),
                    doc.metadata.get("page"),
                    doc.page_content[:120],
                )
                if key not in seen:
                    leftovers.append((doc, score))

        leftovers.sort(key=lambda item: item[1], reverse=True)
        for doc, score in leftovers:
            if len(merged) >= max_total:
                break
            add_chunk(doc, score)

        # Stable ordering: group by source so the LLM sees every document represented
        merged.sort(
            key=lambda item: (
                filter_sources.index(item[0].metadata.get("source", ""))
                if item[0].metadata.get("source") in filter_sources
                else 999,
                -item[1],
            )
        )

        safe_print(
            "Retrieved chunks per source: "
            + ", ".join(
                f"{src}={sum(1 for d, _ in merged if d.metadata.get('source') == src)}"
                for src in filter_sources
            )
        )

        return merged
