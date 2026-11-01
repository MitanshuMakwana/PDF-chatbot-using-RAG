import os
import traceback
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv
from semantic_cache import SemanticCache

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
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
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Lazy-loaded so HTML/CSS load instantly (embeddings load only on first upload/chat)
_assistant = None


def get_assistant():
    global _assistant
    if _assistant is None:
        from rag import RAGAssistant

        _assistant = RAGAssistant(persist_dir=os.path.join(BASE_DIR, "chroma_db"))
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
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/documents")
def get_documents():
    return {"documents": get_assistant().list_documents()}


@app.get("/api/document-content")
def document_content():
    try:
        data = get_assistant().db.get()
        docs = data.get("documents", [])
        text = "\n\n".join(docs[:5]) if docs else "No document content available."
        return {"content": text}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected")

    if not allowed_file(file.filename):
        raise HTTPException(status_code=400, detail="Only .pdf files are supported")

    safe_filename = os.path.basename(file.filename)
    filepath = os.path.join(UPLOAD_DIR, safe_filename)

    contents = await file.read()
    with open(filepath, "wb") as f:
        f.write(contents)

    try:
        assistant = get_assistant()
        chunk_count = await run_in_threadpool(assistant.add_document, filepath, safe_filename)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Indexing failed: {str(exc)}")

    return {"message": f"Successfully indexed {safe_filename}", "chunks": chunk_count}


@app.post("/api/chat")
async def chat(payload: ChatRequest):
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
        )
    except Exception as exc:
        traceback.print_exc()
        message = str(exc)
        if any(
            token in message.lower()
            for token in ("429", "resource_exhausted", "rate limit", "quota")
        ):
            raise HTTPException(
                status_code=429,
                detail=(
                    "Gemini API rate limit reached. Please wait a few seconds "
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
        port=5000,
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
