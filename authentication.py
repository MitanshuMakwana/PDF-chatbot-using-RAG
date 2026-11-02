"""Verify Supabase access tokens and expose the authenticated user to FastAPI."""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urljoin

import httpx
from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)


def require_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Validate the bearer token with Supabase Auth and return its user record."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Please sign in to continue.")

    project_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    anon_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not project_url or not anon_key:
        logger.error("Supabase authentication is not configured on the API")
        raise HTTPException(status_code=503, detail="Sign-in is not configured on the server.")

    token = authorization.split(None, 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")

    try:
        response = httpx.get(
            urljoin(project_url + "/", "auth/v1/user"),
            headers={"apikey": anon_key, "Authorization": f"Bearer {token}"},
            timeout=8.0,
        )
    except httpx.RequestError as exc:
        logger.warning("Supabase token verification request failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not verify your session. Try again.") from exc

    if response.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")
    if response.status_code >= 500:
        logger.error("Supabase Auth returned status %s", response.status_code)
        raise HTTPException(status_code=503, detail="Sign-in service is temporarily unavailable.")
    if response.status_code != 200:
        logger.error("Unexpected Supabase Auth verification status %s", response.status_code)
        raise HTTPException(status_code=503, detail="Could not verify your session.")

    try:
        user = response.json()
    except ValueError as exc:
        logger.error("Supabase Auth returned an invalid user response")
        raise HTTPException(status_code=503, detail="Could not verify your session.") from exc

    if not isinstance(user, dict) or not isinstance(user.get("id"), str) or not user["id"]:
        raise HTTPException(status_code=401, detail="The sign-in session is invalid.")
    return user
