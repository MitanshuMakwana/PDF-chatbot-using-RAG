"""Focused tests for Supabase token verification and protected API routes."""

from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException

from authentication import require_user


class SupabaseAuthenticationTests(unittest.TestCase):
    @patch.dict(os.environ, {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_ANON_KEY": "public-test-key"})
    def test_rejects_missing_bearer_token(self):
        with self.assertRaises(HTTPException) as context:
            require_user(None)
        self.assertEqual(context.exception.status_code, 401)

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_server_configuration_fails_closed(self):
        with self.assertRaises(HTTPException) as context:
            require_user("Bearer valid-looking-token")
        self.assertEqual(context.exception.status_code, 503)

    @patch.dict(os.environ, {"SUPABASE_URL": "https://example.supabase.co/", "SUPABASE_ANON_KEY": "public-test-key"})
    @patch("authentication.httpx.get")
    def test_valid_token_returns_verified_supabase_user(self, mock_get):
        mock_get.return_value = Mock(status_code=200, json=lambda: {"id": "user-123", "email": "person@example.com"})
        user = require_user("Bearer signed-access-token")
        self.assertEqual(user["id"], "user-123")
        mock_get.assert_called_once_with(
            "https://example.supabase.co/auth/v1/user",
            headers={"apikey": "public-test-key", "Authorization": "Bearer signed-access-token"},
            timeout=8.0,
        )

    @patch.dict(os.environ, {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_ANON_KEY": "public-test-key"})
    @patch("authentication.httpx.get")
    def test_invalid_token_is_unauthorized(self, mock_get):
        mock_get.return_value = Mock(status_code=401)
        with self.assertRaises(HTTPException) as context:
            require_user("Bearer expired-token")
        self.assertEqual(context.exception.status_code, 401)

    @patch.dict(os.environ, {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_ANON_KEY": "public-test-key"})
    @patch("authentication.httpx.get", side_effect=httpx.ConnectError("offline"))
    def test_auth_provider_outage_returns_service_unavailable(self, _mock_get):
        with self.assertRaises(HTTPException) as context:
            require_user("Bearer token")
        self.assertEqual(context.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
