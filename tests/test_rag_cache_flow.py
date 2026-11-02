"""RAG integration-flow tests. Full app dependencies are required to run these."""

from __future__ import annotations

import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from semantic_cache import SemanticCache

RAG_AVAILABLE = all(importlib.util.find_spec(name) for name in (
    "langchain_community", "langchain_google_genai", "langchain_core", "langchain_text_splitters"
))
if RAG_AVAILABLE:
    from rag import RAGAssistant


@unittest.skipUnless(RAG_AVAILABLE, "Install requirements.txt to run RAG integration-flow tests")
class RAGCacheFlowTests(unittest.TestCase):
    def setUp(self):
        self.assistant = RAGAssistant.__new__(RAGAssistant)
        self.assistant.embeddings = MagicMock()
        self.assistant.embeddings.embed_query.return_value = [1.0, 0.0]
        self.assistant.semantic_cache = MagicMock(spec=SemanticCache)
        self.assistant.semantic_cache.client = object()
        self.assistant.semantic_cache.is_cacheable_question.return_value = True
        self.assistant.semantic_cache.collection_id.return_value = "collection-hash"
        self.assistant.semantic_cache.collection_fingerprint.return_value = "content-hash"
        self.assistant.db = MagicMock()
        self.assistant.db.get.return_value = {
            "documents": ["source content"],
            "metadatas": [{"source": "source.pdf", "page": 1}],
        }
        self.document = SimpleNamespace(
            metadata={"source": "source.pdf", "page": 1},
            page_content="Source text",
        )
        self.assistant.llm = MagicMock()
        self.assistant.llm.invoke.return_value = SimpleNamespace(content="Generated answer")

    def test_miss_runs_retrieval_and_generation_then_stores_result(self):
        self.assistant.semantic_cache.lookup.return_value = None
        self.assistant._retrieve = MagicMock(return_value=[(self.document, 0.9)])

        result = self.assistant.query("Summarize the source document", ["source.pdf"])

        self.assistant._retrieve.assert_called_once()
        self.assistant.llm.invoke.assert_called_once()
        self.assistant.semantic_cache.store.assert_called_once()
        self.assertEqual(result["answer"], "Generated answer")

    def test_hit_skips_chroma_vector_retrieval_and_gemini(self):
        cached_result = {"answer": "Previously generated answer", "sources": []}
        self.assistant.semantic_cache.lookup.return_value = cached_result
        self.assistant._retrieve = MagicMock()

        result = self.assistant.query("Summarize the source document", ["source.pdf"])

        self.assistant._retrieve.assert_not_called()
        self.assistant.llm.invoke.assert_not_called()
        self.assistant.semantic_cache.store.assert_not_called()
        self.assertEqual(result["answer"], cached_result["answer"])

    def test_empty_retrieval_is_not_cached(self):
        self.assistant.semantic_cache.lookup.return_value = None
        self.assistant._retrieve = MagicMock(return_value=[])

        result = self.assistant.query("Summarize the source document", ["source.pdf"])

        self.assistant.llm.invoke.assert_not_called()
        self.assistant.semantic_cache.store.assert_not_called()
        self.assertEqual(result["sources"], [])

    def test_retrieval_filter_always_includes_authenticated_tenant(self):
        assistant = RAGAssistant.__new__(RAGAssistant)
        assistant.db = MagicMock()
        assistant.db.similarity_search_with_relevance_scores.return_value = []

        assistant._retrieve("question", ["private.pdf"], tenant_id="tenant-42")

        assistant.db.similarity_search_with_relevance_scores.assert_called_once_with(
            "question", k=6,
            filter={"$and": [{"tenant_id": "tenant-42"}, {"source": "private.pdf"}]},
        )


if __name__ == "__main__":
    unittest.main()
