#  RAG Assistant using FastAPI, Gemini & ChromaDB

A simple Retrieval-Augmented Generation (RAG) application that allows users to upload PDF documents and ask questions based on their content.

The application extracts text from uploaded PDFs, creates embeddings, stores them in ChromaDB, retrieves relevant document chunks, and uses Google's Gemini model to generate answers.

---

##  Features

- Upload PDF documents
- Automatic text extraction
- Intelligent text chunking
- Vector embeddings using Hugging Face
- ChromaDB vector storage
- Semantic document retrieval
- Question answering using Gemini 2.5 Flash
- FastAPI backend
- Simple web interface
- Dark theme UI

---

## Tech Stack

### Backend
- FastAPI
- Python

### AI / RAG
- Google Gemini 2.5 Flash
- Hugging Face Embeddings
- LangChain
- ChromaDB

### Document Processing
- PyPDF

### Frontend
- HTML
- CSS
- JavaScript

---

##  Project Structure

```text
rag-assistant/
│
├── chroma_db/          # Vector database
├── uploads/            # Uploaded PDFs
│
├── static/
│   ├── style.css
│   └── script.js
│
├── templates/
│   └── index.html
│
├── rag.py              # RAG logic
├── main.py             # FastAPI application
├── requirements.txt
├── .env
└── README.md
```

---

##  How It Works

### Step 1: Upload PDF

User uploads a PDF document.

### Step 2: Text Extraction

The PDF is loaded and text is extracted using:

```python
PyPDFLoader
```

### Step 3: Text Chunking

The document is divided into smaller chunks.

```python
chunk_size = 3000
chunk_overlap = 300
```

### Step 4: Embedding Generation

Each chunk is converted into vector embeddings using:

```python
sentence-transformers/all-MiniLM-L6-v2
```

### Step 5: Store in ChromaDB

Embeddings are stored in:

```text
chroma_db/
```

### Step 6: User Question

User asks a question.

### Step 7: Similarity Search

ChromaDB retrieves the most relevant chunks.

### Step 8: Gemini Response

Relevant chunks are passed to Gemini 2.5 Flash which generates the final answer.

---

##  RAG Pipeline

```text
PDF
 ↓
Text Extraction
 ↓
Chunking
 ↓
HuggingFace Embeddings
 ↓
ChromaDB
 ↓
Similarity Search
 ↓
Gemini 2.5 Flash
 ↓
Answer
```

---

##  Installation

### Clone Repository

```bash
git clone https://github.com/YOUR_USERNAME/rag-assistant.git

cd rag-assistant
```

### Create Virtual Environment

```bash
python -m venv venv
```

### Activate Environment

Windows:

```bash
venv\Scripts\activate
```

Linux/Mac:

```bash
source venv/bin/activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

---

##  Environment Variables

Create a `.env` file:

```env
GOOGLE_API_KEY=YOUR_GOOGLE_API_KEY
```

---

##  Run Application

```bash
uvicorn main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

---

##  Application Workflow

1. Upload PDF
2. PDF gets indexed
3. Ask questions
4. Receive context-aware answers

---

## Example Questions

```text
Summarize the document.

What are the key responsibilities mentioned?

What technologies are discussed?

Explain section 3.
```

---

## Future Improvements

- Multiple document support
- PDF preview
- Source citations
- Chat history
- User authentication
- Document deletion
- Streaming responses
- Docker deployment

---

## Learning Outcomes

This project demonstrates:

- Retrieval-Augmented Generation (RAG)
- Vector Databases
- Embeddings
- Semantic Search
- Large Language Models
- FastAPI Development
- AI Application Development

---

## Author

Mitanshu Makwana

Information Technology Engineering

LDRP Institute of Technology and Research
