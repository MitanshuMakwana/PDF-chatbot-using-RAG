"""API smoke tests proving document routes fail closed without a session."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from authentication import require_user


class ProtectedApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Keep test imports independent of a developer's configured data directory.
        cls.previous_data_dir = os.environ.get("RAG_DATA_DIR")
        os.environ["RAG_DATA_DIR"] = str(Path(tempfile.gettempdir()) / "rag-auth-api-tests")
        import main

        cls.routes = {route.path: route for route in main.app.routes if hasattr(route, "dependant")}

    @classmethod
    def tearDownClass(cls):
        if cls.previous_data_dir is None:
            os.environ.pop("RAG_DATA_DIR", None)
        else:
            os.environ["RAG_DATA_DIR"] = cls.previous_data_dir

    def test_document_endpoints_require_a_signed_in_user(self):
        protected_paths = (
            "/api/documents",
            "/api/document-content",
            "/api/chat",
            "/api/upload",
            "/api/documents/{filename}",
        )
        for path in protected_paths:
            with self.subTest(path=path):
                route = self.routes[path]
                self.assertIn(require_user, [dependency.call for dependency in route.dependant.dependencies])


if __name__ == "__main__":
    unittest.main()
