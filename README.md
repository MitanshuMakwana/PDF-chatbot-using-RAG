# RAG Assistant — PDF Chatbot using FastAPI, Ollama/Gemini & ChromaDB

A Retrieval-Augmented Generation (RAG) web app that lets you upload PDF documents and ask natural-language questions. Answers are grounded in your uploaded files using semantic search and a configurable Ollama or Gemini model.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.139-green)
![Gemini](https://img.shields.io/badge/Gemini-2.5%20Flash-orange)

---

## Features

- **PDF upload & indexing** — drag-and-drop or browse; text extracted with PyMuPDF
- **Session-scoped Q&A** — answers use only PDFs uploaded in the current browser session
- **Multi-document support** — per-document retrieval so one file cannot crowd out another
- **Human-readable answers** — tailored responses (lists, summaries, comparisons) via prompt engineering
- **Refined chat UI** — neutral dark-grey glass panels, restrained `#77DD77` accents, and no green card glow
- **Readable chat actions** — sent-message bubbles use the same light-green tint as Upload & Index and Send
- **Source details on demand** — hover or focus the source dot on an answer to see its PDF filename and page number(s)
- **Provider choice** — Ollama Cloud, local Ollama, or Gemini selected through environment variables
- **Semantic answer cache** — optional Redis Search vector cache, scoped to the active PDFs and their indexed content version
- **Rate-limit resilience** — exponential backoff retries for provider rate limits
- **Windows-safe text handling** — sanitizes PDF bullets/symbols (e.g. `\uf0b7`) that break cp1252 consoles
- **Lazy model loading** — page loads instantly; embeddings load on first upload/chat

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI, Uvicorn |
| LLM | Ollama Cloud/local or Google Gemini (configurable) |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` |
| Vector DB | ChromaDB |
| Semantic cache | Redis Search vector index (optional; ChromaDB remains the document store) |
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
│   ├── style.css       # Dark glass theme, accent colors, and responsive layout
│   └── script.js       # Upload, chat, session document tracking
├── templates/
│   └── index.html      # Main web page
├── semantic_cache.py   # Redis vector cache, TTL, lookup, and invalidation
├── rag.py              # RAG pipeline, retrieval, LLM calls
├── main.py             # FastAPI routes & server config
├── tests/               # Semantic cache and RAG cache-flow tests
├── render.yaml          # Render backend deployment blueprint
├── vercel.json          # Vercel frontend deployment config
├── requirements.txt
├── .env                # Local environment settings and secrets (not committed)
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
Embed question once
      ↓
Redis semantic cache lookup (active PDF collection and content fingerprint)
      ↓ cache miss (or Redis unavailable)
Per-document ChromaDB similarity search (multi-PDF mode)
      ↓
Build labeled context blocks
      ↓
Configured Ollama or Gemini model generates answer (with retry on rate limits)
      ↓
Cache eligible answer in Redis with a TTL
      ↓
Formatted markdown response with hoverable source details
```

Redis is an optional answer cache, not a replacement for ChromaDB. If Redis is unavailable, questions continue through the normal ChromaDB and LLM flow. Cache entries are isolated by the active document set and its content fingerprint, and are invalidated when indexed documents change.

### Multi-document retrieval

When multiple PDFs are active, the app does **not** run a single global top-k search (which biases toward the largest or most similar file). Instead it:

1. Retrieves top chunks **from each PDF separately**
2. Guarantees a **minimum number of chunks per document**
3. Merges and labels context so the configured LLM can answer per-file, combined, or comparative questions

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

Create or edit `.env` in the project root and set the provider. For Ollama Cloud:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=https://ollama.com/v1
OLLAMA_API_KEY=your_ollama_api_key
OLLAMA_MODEL=gemma4:31b
```

For local Ollama, use `OLLAMA_BASE_URL=http://localhost:11434/v1` and `OLLAMA_API_KEY=ollama`. For Gemini, set `LLM_PROVIDER=gemini` and `GOOGLE_API_KEY`. Keep provider keys on the backend; never put them in frontend JavaScript. Add `REDIS_URL` to enable hosted Redis semantic caching.

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
| `POST` | `/api/upload` | Upload and index a PDF (authenticated) |
| `POST` | `/api/chat` | Ask a question (`message`, `documents[]`; authenticated) |
| `GET` | `/api/documents` | List the signed-in user's indexed PDFs |
| `DELETE` | `/api/documents/{filename}` | Delete one of the signed-in user's PDFs |
| `GET` | `/api/document-content` | Sample the signed-in user's stored chunk text (debug) |

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
| `LLM_MAX_RETRIES` | `5` | Provider rate-limit retry attempts |
| `LLM_BASE_DELAY_SEC` | `2.0` | Base delay for exponential backoff |

### Hosted Redis semantic cache

The semantic answer cache requires Redis Search with vector support; an ordinary Redis key-value database is not sufficient. The application accepts hosted Redis connection URLs through `REDIS_URL`, including TLS URLs using `rediss://`. Do not commit `.env` or share the connection URL.

1. Create a hosted Redis database whose feature list includes Redis Search/vector search.
2. Copy its endpoint, port, username, and password, and enable TLS when the plan supports it.
3. Set `REDIS_URL` in `.env` using the provider's connection URL. If composing the URL yourself, URL-encode special characters in credentials.
4. Start the app. On startup it connects and creates `rag_semantic_cache_idx` when needed.
5. Verify connectivity and index creation by running `python -m unittest discover -s tests -v` with `RUN_REDIS_INTEGRATION=1` and `REDIS_URL` set in the current shell.

If Redis is unreachable, the app logs that the semantic cache is unavailable and continues through the existing ChromaDB RAG flow.

Optional cache settings can also be placed in `.env`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEMANTIC_CACHE_ENABLED` | `true` | Enable or disable caching |
| `SEMANTIC_CACHE_SIMILARITY_THRESHOLD` | `0.90` | Minimum similarity for a cache hit |
| `SEMANTIC_CACHE_TTL_SECONDS` | `86400` | Cache entry lifetime |
| `SEMANTIC_CACHE_SCOPE_ID` | `local-default` | Isolate entries by deployment or tenant scope |

---

## Hosting with login and per-user documents

Supabase Auth provides Google OAuth and email/password sign-in. The browser sends a Supabase access token with every API call; FastAPI verifies it with Supabase Auth. The authenticated Supabase user ID is stored on Chroma records and used in every listing, retrieval, deletion, and semantic-cache scope. Users cannot access records that lack their tenant ID.

1. Create a Supabase project. In **Authentication → Providers**, enable Email and Google; configure the Google OAuth credentials with the redirect URL shown by Supabase. Add the local app URL and the Vercel site URL to **Authentication → URL Configuration → Redirect URLs**.
2. Copy the project URL and the public anon/publishable key. Put them in local `.env` as `SUPABASE_URL` and `SUPABASE_ANON_KEY` (never use a service-role key in the frontend).
3. Add `SUPABASE_URL` and `SUPABASE_ANON_KEY` as environment variables in both Render and Vercel. Vercel uses them at build time to generate the public browser configuration; Render uses them to verify access tokens.
4. Keep `RAG_API_BASE_URL` set in Vercel and set Render `CORS_ORIGINS` to the exact Vercel origin. Redeploy both services after changing these values.
5. On Render's Free plan, `RAG_DATA_DIR=/tmp/rag-data` is ephemeral. Uploaded PDFs and Chroma data can be lost when the service restarts or is replaced. Use persistent storage for lasting document storage.

`render.yaml` defines the Free service settings and environment variable names. Add model and Redis secrets in the Render dashboard; do not commit credentials. `.env.example` lists the local variables without real credentials.

The root page contains only the frontend shell; document APIs require a valid Supabase user token. Existing Chroma records without a `tenant_id` remain inaccessible through authenticated endpoints. Existing deployments will not display the sign-in form correctly until the Supabase URL and public key are configured on both hosts.

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
