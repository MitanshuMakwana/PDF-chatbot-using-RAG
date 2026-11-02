import os
import hashlib
import json
import logging
import traceback
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv
from semantic_cache import SemanticCache
from authentication import require_user

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
DATA_DIR = os.getenv("RAG_DATA_DIR", BASE_DIR).strip() or BASE_DIR
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
ALLOWED_EXTENSIONS = {"pdf"}

os.makedirs(UPLOAD_DIR, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    cache = SemanticCache()
    cache.start()
    app.state.semantic_cache = cache
    try:
        yield
    finally:
        cache.close()


app = FastAPI(title="RAG Assistant", lifespan=lifespan)
cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Lazy-loaded so HTML/CSS load instantly (embeddings load only on first upload/chat)
_assistant = None


def get_assistant():
    global _assistant
    if _assistant is None:
        from rag import RAGAssistant

        _assistant = RAGAssistant(persist_dir=os.path.join(DATA_DIR, "chroma_db"))
        _assistant.semantic_cache = getattr(app.state, "semantic_cache", None)
    return _assistant


class ChatRequest(BaseModel):
    message: str
    documents: Optional[List[str]] = None


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # Serve HTML immediately — do not touch Chroma/embeddings on page load
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={},
    )


@app.get("/config.js", response_class=PlainTextResponse)
def frontend_config():
    # The anonymous key is public by design; access control is enforced by Supabase RLS
    # for Supabase resources and by bearer-token verification on this API.
    config = {
        "url": os.getenv("SUPABASE_URL", "").strip(),
        "anonKey": os.getenv("SUPABASE_ANON_KEY", "").strip(),
    }
    return "window.RAG_API_BASE_URL = '';\nwindow.RAG_SUPABASE_CONFIG = " + json.dumps(config) + ";"


@app.get("/api/documents")
def get_documents(user: dict = Depends(require_user)):
    return {"documents": get_assistant().list_documents(user["id"])}


@app.get("/api/document-content")
def document_content(user: dict = Depends(require_user)):
    try:
        data = get_assistant().db.get(where={"tenant_id": user["id"]})
        docs = data.get("documents", [])
        text = "\n\n".join(docs[:5]) if docs else "No document content available."
        return {"content": text}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), user: dict = Depends(require_user)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected")

    if not allowed_file(file.filename):
        raise HTTPException(status_code=400, detail="Only .pdf files are supported")

    safe_filename = os.path.basename(file.filename)
    assistant = get_assistant()
    if safe_filename in assistant.list_documents(user["id"]):
        raise HTTPException(status_code=409, detail="A PDF with this filename is already in your account.")

    tenant_storage = hashlib.sha256(user["id"].encode("utf-8")).hexdigest()
    tenant_upload_dir = os.path.join(UPLOAD_DIR, tenant_storage)
    os.makedirs(tenant_upload_dir, exist_ok=True)
    filepath = os.path.join(tenant_upload_dir, safe_filename)

    contents = await file.read()
    with open(filepath, "wb") as f:
        f.write(contents)

    try:
        chunk_count = await run_in_threadpool(
            assistant.add_document, filepath, safe_filename, user["id"]
        )
    except Exception as exc:
        try:
            os.remove(filepath)
        except OSError:
            pass
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Indexing failed: {str(exc)}")

    return {"message": f"Successfully indexed {safe_filename}", "chunks": chunk_count}


@app.delete("/api/documents/{filename}")
async def delete_document(filename: str, user: dict = Depends(require_user)):
    safe_filename = os.path.basename(filename)
    if not safe_filename or safe_filename != filename:
        raise HTTPException(status_code=400, detail="Invalid document name.")

    assistant = get_assistant()
    if safe_filename not in assistant.list_documents(user["id"]):
        raise HTTPException(status_code=404, detail="Document not found in your account.")

    try:
        await run_in_threadpool(assistant.delete_document, safe_filename, user["id"])
    except Exception as exc:
        logger.exception("Document deletion failed")
        raise HTTPException(status_code=500, detail="Could not remove the document.") from exc

    tenant_storage = hashlib.sha256(user["id"].encode("utf-8")).hexdigest()
    filepath = os.path.join(UPLOAD_DIR, tenant_storage, safe_filename)
    try:
        os.remove(filepath)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Could not remove uploaded PDF file %s", filepath, exc_info=True)
    return {"message": f"Removed {safe_filename}"}


@app.post("/api/chat")
async def chat(payload: ChatRequest, user: dict = Depends(require_user)):
    question = payload.message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    active_documents = [
        doc.strip()
        for doc in (payload.documents or [])
        if doc and doc.strip()
    ]

    if not active_documents:
        raise HTTPException(
            status_code=400,
            detail="Please upload at least one PDF before asking questions.",
        )

    try:
        result = await run_in_threadpool(
            get_assistant().query,
            question=question,
            filter_sources=active_documents,
            tenant_id=user["id"],
        )
    except Exception as exc:
        traceback.print_exc()
        message = str(exc)
        if any(
            token in message.lower()
            for token in ("429", "resource_exhausted", "rate limit", "quota")
        ):
            provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
            label = "Ollama" if provider == "ollama" else "Gemini"
            raise HTTPException(
                status_code=429,
                detail=(
                    f"{label} API rate limit reached. Please wait a few seconds "
                    "and try again."
                ),
            )
        raise HTTPException(status_code=500, detail=f"Query failed: {message}")

    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5000")),
        reload=True,
        # Editing CSS/JS/HTML must not restart the server / embedding model
        reload_includes=["*.py"],
        reload_excludes=[
            "static/*",
            "templates/*",
            "uploads/*",
            "chroma_db/*",
            "venv/*",
            "*.css",
            "*.js",
            "*.html",
            "*.md",
        ],
    )
