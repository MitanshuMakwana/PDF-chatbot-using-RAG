"""Build the existing template and static assets for Vercel's static hosting."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "vercel_output"


def main() -> None:
    api_base_url = os.getenv("RAG_API_BASE_URL", "").strip().rstrip("/")
    if not api_base_url.startswith(("https://", "http://")):
        raise SystemExit("Set RAG_API_BASE_URL to the deployed FastAPI service URL before building.")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "templates" / "index.html", OUTPUT / "index.html")
    shutil.copytree(ROOT / "static", OUTPUT / "static", dirs_exist_ok=True)
    (OUTPUT / "config.js").write_text(
        "window.RAG_API_BASE_URL = " + json.dumps(api_base_url) + ";\n"
        + "window.RAG_SUPABASE_CONFIG = " + json.dumps({
            "url": os.getenv("SUPABASE_URL", "").strip(),
            "anonKey": os.getenv("SUPABASE_ANON_KEY", "").strip(),
        }) + ";\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
