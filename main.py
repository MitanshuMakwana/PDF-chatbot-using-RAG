import os

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
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

# One shared assistant instance for the life of the process.
assistant = RAGAssistant(persist_dir=os.path.join(BASE_DIR, "chroma_db"))


class ChatRequest(BaseModel):
    message: str


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

    data = assistant.db.get()

    docs = data.get("documents", [])

    text = "\n\n".join(docs[:5])

    return {"content": text}

@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected")

    if not allowed_file(file.filename):
        raise HTTPException(
            status_code=400, detail="Only .pdf, .txt, and .md files are supported"
        )

    filepath = os.path.join(UPLOAD_DIR, file.filename)
    contents = await file.read()
    with open(filepath, "wb") as f:
        f.write(contents)

    try:
        chunk_count = assistant.add_document(filepath, file.filename)
    except Exception as exc:
        import traceback

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=str(exc)
        )

    return {"message": f"Indexed {file.filename}", "chunks": chunk_count}


@app.post("/api/chat")
def chat(payload: ChatRequest):
    question = payload.message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Message is required")

    try:
        result = assistant.query(question)
    except Exception as exc:
        import traceback

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=str(exc)
        )

    return JSONResponse(result)


if __name__ == "__main__":
    import uvicorn

    # Single command to run everything: python main.py
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
