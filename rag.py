import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

load_dotenv()


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
            temperature=0,
        )

    def add_document(self, filepath, filename):
        loader = PyPDFLoader(filepath)
        documents = loader.load()

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=3000,
            chunk_overlap=300
        )

        chunks = splitter.split_documents(documents)
        chunks = chunks[:100]

        for chunk in chunks:
            chunk.metadata["source"] = filename

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

    def query(self, question):
        docs = self.db.similarity_search(question, k=4)

        if not docs:
            return {
                "answer": "No documents found.",
                "sources": []
            }

        context = "\n\n".join(
            doc.page_content for doc in docs
        )

        prompt = f"""
Answer ONLY from the provided context.

If the answer is not present in the context,
say "I could not find that information in the document."

Context:
{context}

Question:
{question}
"""

        response = self.llm.invoke(prompt)

        sources = []

        for doc in docs:
            sources.append(
                {
                    "source": doc.metadata.get("source", "Unknown")
                }
            )

        return {
            "answer": response.content,
            "sources": sources
        }