import os
import re

from dotenv import load_dotenv
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv()


def format_answer(text: str) -> str:
    """Normalize LLM markdown so sections and lists render cleanly."""
    if not text:
        return text

    text = text.strip()

    # Put block headings on their own line when the model runs them inline.
    text = re.sub(r"([^\n])\s*(\*\*[^*\n]+:\*\*)", r"\1\n\n\2", text)
    text = re.sub(r"(\*\*[^*\n]+\*\*)\s*-\s+", r"\1\n\n- ", text)

    # Convert inline dash lists into one item per line.
    text = re.sub(r"(?<!\n)\s+-\s+(?=[A-Za-z0-9])", "\n- ", text)

    # Collapse excessive blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


class RAGAssistant:
    def __init__(self, persist_dir):
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )

        self.db = Chroma(
            persist_directory=persist_dir,
            embedding_function=self.embeddings,
        )

        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.4,
            top_p=0.9,
        )

    def add_document(self, filepath, filename):
        loader = PyMuPDFLoader(filepath)
        documents = loader.load()

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1200,
            chunk_overlap=300,
            separators=["\n\n", "\n", ".", " ", ""]
        )

        chunks = splitter.split_documents(documents)

        for chunk in chunks:
            chunk.metadata["source"] = filename
            
            if "page" in chunk.metadata:
                chunk.metadata["page"] += 1

        self.db.add_documents(chunks)

        return len(chunks)

    def list_documents(self):
        try:
            data = self.db.get()

            sources = set()

            for meta in data["metadatas"]:
                if meta and "source" in meta:
                    sources.add(meta["source"])

            return sorted(list(sources))

        except Exception:
            return []

    def query(self, question, filter_sources=None):
        # RELEVANCE_THRESHOLD = 0.5

        if filter_sources:
            if len(filter_sources) == 1:
                chroma_filter = {"source": filter_sources[0]}
            else:
                chroma_filter = {"source": {"$in": filter_sources}}

            docs_scores = self.db.similarity_search_with_relevance_scores(
                question,
                k=min(6 * len(filter_sources), 12),
                filter=chroma_filter,
            )
        else:
            docs_scores = self.db.similarity_search_with_relevance_scores(
                question,
                k=6
            )

        # Debug scores
        for doc, score in docs_scores:
            print(
                f"score={score:.3f} | "
                f"source={doc.metadata.get('source')} | "
                f"{doc.page_content[:80]}"
            )

        docs = [
            doc
            for doc, score in docs_scores
            # if score >= RELEVANCE_THRESHOLD
        ]

        if not docs:
            return {
                "answer": "No relevant documents found.",
                "sources": []
            }
            
        # DEBUG: Print retrieved chunks
        for i, doc in enumerate(docs, 1):
            print("\n" + "=" * 60)
            print(f"Chunk {i}")
            print(f"Source: {doc.metadata.get('source')}")
            print(f"Page: {doc.metadata.get('page')}")
            print(doc.page_content[:500])

        context = "\n\n---\n\n".join(
            doc.page_content for doc in docs
        )

        system_prompt = """You are a helpful assistant that answers questions about uploaded documents such as resumes, reports, and manuals.

CORE RULES:
- Use ONLY the provided context. Never invent or assume information.
- Never mention documents, sources, context, excerpts, page numbers, or file names.
- Match your tone and structure to what the user actually asked.
- Write like a knowledgeable human, not a form or database dump.

HOW TO TAILOR RESPONSES:

1. Identity questions ("whose resume is this?", "who is this?"):
   Start with a natural sentence identifying the person and their role or focus.
   Example: "This is the resume of Mitanshu Makwana, a developer with experience in generative AI and full-stack web development."

2. Skill or category questions ("skills?", "what technologies?"):
   Group related items under short headings. Use one bullet per item.
   Put a blank line between each section.

3. "Top N" or ranked questions:
   Answer directly in one sentence, then list exactly N items as bullets with a brief note if helpful.

4. Count + explanation questions ("how many projects and explain one"):
   State the count first, then explain the requested item in 2-4 clear sentences covering purpose, tech stack, and key features.

5. Short factual questions:
   Give a direct answer in 1-2 sentences. Do not over-format.

FORMATTING RULES:
- Use markdown with blank lines between paragraphs and sections.
- Use "-" bullet lists for enumerations. Never cram multiple bullets on one line.
- Use **bold** only for short section labels or project names, not for every field.
- Do not use "*" for bullets.
- If information is missing, say so briefly. Do not guess.

BAD (never do this):
**Name:** John Doe
**Total Projects:** 3 **Project Explanation** Learnsy is a platform...

GOOD:
This is the resume of John Doe, a data engineer focused on ML pipelines.

There are 3 projects listed. Here is one full-stack project:

**Learnsy** — An e-learning platform with separate faculty and student dashboards. Faculty can upload videos, notes, and documents. Built with React on the frontend and Node.js with MongoDB on the backend."""

        human_prompt = f"""Context:
{context}

Question:
{question}

Answer in a natural, tailored way following the rules above:"""

        response = self.llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ])

        # Collect unique sources
        unique_sources = {}
        for doc in docs:
            src = doc.metadata.get("source", "Unknown")
            page = doc.metadata.get("page", None)
            if src not in unique_sources:
                unique_sources[src] = set()
            if page is not None:
                unique_sources[src].add(page)

        sources_summary = [
            {
                "source": src,
                "pages": sorted(list(pages)) if pages else "N/A"
            }
            for src, pages in unique_sources.items()
        ]
        
        answer = format_answer(response.content)

        return {
            "answer": answer,
            "sources": sources_summary
        }

 