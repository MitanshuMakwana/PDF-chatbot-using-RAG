# RAG Assistant — PDF Chatbot using FastAPI, Gemini & ChromaDB

A Retrieval-Augmented Generation (RAG) web app that lets you upload PDF documents and ask natural-language questions. Answers are grounded in your uploaded files using semantic search and Google Gemini.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.139-green)
![Gemini](https://img.shields.io/badge/Gemini-2.5%20Flash-orange)

---

## Features

- **PDF upload & indexing** — drag-and-drop or browse; text extracted with PyMuPDF
- **Session-scoped Q&A** — answers use only PDFs uploaded in the current browser session
- **Multi-document support** — per-document retrieval so one file cannot crowd out another
- **Human-readable answers** — tailored responses (lists, summaries, comparisons) via prompt engineering
- **Modern dark UI** — sidebar upload panel, chat interface, quick prompts, copy-to-clipboard
- **Rate-limit resilience** — exponential backoff retries for Gemini `429 RESOURCE_EXHAUSTED`
- **Windows-safe text handling** — sanitizes PDF bullets/symbols (e.g. `\uf0b7`) that break cp1252 consoles
- **Lazy model loading** — page loads instantly; embeddings load on first upload/chat

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI, Uvicorn |
| LLM | Google Gemini 2.5 Flash |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` |
| Vector DB | ChromaDB |
| RAG framework | LangChain |
| PDF parsing | PyMuPDF (`PyMuPDFLoader`) |
| Frontend | HTML, CSS, JavaScript, Marked.js |

---

## Project Structure

```text
rag-assistant/
├── chroma_db/          # Persisted vector store (auto-created)
├── uploads/            # Uploaded PDF files (auto-created)
├── static/
│   ├── style.css       # Dark-themed UI styles
│   └── script.js       # Upload, chat, session document tracking
├── templates/
│   └── index.html      # Main web page
├── rag.py              # RAG pipeline, retrieval, LLM calls
├── main.py             # FastAPI routes & server config
├── requirements.txt
├── .env                # API keys (not committed)
└── README.md
```

---

## How It Works

```text
Upload PDF(s)
      ↓
Extract text (PyMuPDF) + sanitize symbols
      ↓
Chunk text (1200 chars, 300 overlap)
      ↓
Embed chunks (HuggingFace MiniLM)
      ↓
Store in ChromaDB (with source metadata)
      ↓
User asks a question
      ↓
Per-document similarity search (multi-PDF mode)
      ↓
Build labeled context blocks
      ↓
Gemini generates answer (with retry on rate limits)
      ↓
Formatted markdown response in chat UI
```

### Multi-document retrieval

When multiple PDFs are active, the app does **not** run a single global top-k search (which biases toward the largest or most similar file). Instead it:

1. Retrieves top chunks **from each PDF separately**
2. Guarantees a **minimum number of chunks per document**
3. Merges and labels context so Gemini can answer per-file, combined, or comparative questions

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/MitanshuMakwana/PDF-chatbot-using-RAG.git
cd PDF-chatbot-using-RAG
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

**Windows (PowerShell):**

```bash
venv\Scripts\activate
```

**Linux / macOS:**

```bash
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> First run downloads the embedding model (`all-MiniLM-L6-v2`) and may take a minute.

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
GOOGLE_API_KEY=your_google_gemini_api_key_here
```

Get a key from [Google AI Studio](https://aistudio.google.com/apikey).

---

## Run the Application

```bash
python main.py
```

Or:

```bash
uvicorn main:app --host 127.0.0.1 --port 5000 --reload
```

Open in your browser:

```text
http://127.0.0.1:5000
```

---

## Usage

1. **Upload** one or more PDFs from the left sidebar.
2. Confirm they appear under **Active Documents**.
3. **Ask a question** in the chat box (or use a quick prompt).
4. Answers are scoped to your session's uploaded files only.

### Example questions

- `What is this document about?`
- `List all skills mentioned`
- `Who are the student authors and their enrollment numbers?`
- `Compare both documents`
- `Summarize key points from each PDF`

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web UI |
| `POST` | `/api/upload` | Upload and index a PDF |
| `POST` | `/api/chat` | Ask a question (`message`, `documents[]`) |
| `GET` | `/api/documents` | List indexed document names in ChromaDB |
| `GET` | `/api/document-content` | Sample stored chunk text (debug) |

### Chat request example

```json
{
  "message": "Summarize the key points",
  "documents": ["resume.pdf", "report.pdf"]
}
```

---

## Configuration

Key settings in `rag.py`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `chunk_size` | `1200` | Characters per chunk |
| `chunk_overlap` | `300` | Overlap between chunks |
| `per_doc_k` | `4` | Chunks retrieved per PDF (multi-doc) |
| `min_per_doc` | `2` | Minimum guaranteed chunks per PDF |
| `LLM_MAX_RETRIES` | `5` | Gemini rate-limit retry attempts |
| `LLM_BASE_DELAY_SEC` | `2.0` | Base delay for exponential backoff |

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| Page keeps loading | Server reloading embedding model on CSS saves | Use `python main.py` (reload excludes static files) |
| `429 RESOURCE_EXHAUSTED` | Gemini free-tier rate limit | Wait a few seconds; retries are automatic |
| `charmap` / `\uf0b7` error | PDF bullet symbols on Windows console | Fixed via `sanitize_text()`; re-upload old PDFs |
| Answers only from latest PDF | Global top-k retrieval | Fixed via per-document retrieval |
| `Please upload at least one PDF` | No active session documents | Upload a PDF before chatting |

---

## Development Notes

- RAG assistant is **lazy-loaded** in `main.py` so the homepage responds before embeddings initialize.
- Uvicorn reload watches **`.py` files only** to avoid restarts when editing CSS/JS/HTML.
- Debug retrieval logs print chunk scores and per-source counts to the terminal.

---

## Author

**Mitanshu Makwana**

---

## License

This project is open source. Feel free to use and modify it for learning and personal projects.
