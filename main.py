import os
import traceback
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from rag import RAGAssistant

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"pdf"}

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="RAG Assistant")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Shared assistant instance
assistant = RAGAssistant(persist_dir=os.path.join(BASE_DIR, "chroma_db"))


class ChatRequest(BaseModel):
    message: str
    document: Optional[str] = None  # Optional document filter


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html", {"request": request, "documents": assistant.list_documents()}
    )


@app.get("/api/documents")
def get_documents():
    return {"documents": assistant.list_documents()}


@app.get("/api/document-content")
def document_content():
    try:
        data = assistant.db.get()
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

    # Sanitize filename to prevent directory traversal
    safe_filename = os.path.basename(file.filename)
    filepath = os.path.join(UPLOAD_DIR, safe_filename)

    # Save uploaded file
    contents = await file.read()
    with open(filepath, "wb") as f:
        f.write(contents)

    try:
        # Offload heavy embedding creation to threadpool so event loop remains responsive
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

    try:
        # Offload LLM call and vector search to threadpool
        result = await run_in_threadpool(
            assistant.query, 
            question=question, 
            filter_source=payload.document
        )
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Query failed: {str(exc)}")

    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=5000, reload=True)