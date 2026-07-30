import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyMuPDFLoader
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
            temperature=0.6,
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

    def query(self, question, filter_source=None):
        if filter_source:
            docs = self.db.max_marginal_relevance_search(
                question,
                k=6,
                fetch_k=20,
                filter={"source": filter_source}
            )
        else:
            docs = self.db.max_marginal_relevance_search(
                question,
                k=6,
                fetch_k=20
            )

        if not docs:
            return {
                "answer": "No documents found.",
                "sources": []
            }
        
        # DEBUG: Print retrieved chunks
        for i, doc in enumerate(docs, 1):
            print("\n" + "=" * 60)
            print(f"Chunk {i}")
            print(f"Source: {doc.metadata.get('source')}")
            print(f"Page: {doc.metadata.get('page')}")
            print(doc.page_content[:500])

        context_blocks = []
            
        # Format context with chunk details
        context_blocks = []
        for i, doc in enumerate(docs, start=1):
            source_name = doc.metadata.get("source", "Unknown")
            page_num = doc.metadata.get("page", "N/A")
            context_blocks.append(
                f"[Excerpt {i} | Source: {source_name} | Page: {page_num}]\n{doc.page_content}"
            )

        context = "\n\n---\n\n".join(context_blocks)    

        # context = "\n\n".join(
        #     doc.page_content for doc in docs
        # )

        prompt = f"""
        You are a document question-answering assistant.

        Rules:
        1. Answer naturally in fluent English.
        2. Do not mention document names, file names, source names, chunk numbers, or page numbers unless the user explicitly asks for them.
        3. Write concise but informative answers.
        4. Use only the provided context.
        5. If information is missing, say so politely.
        Context:
        {context}

        Question:
        {question}

        Answer:
        """

        response = self.llm.invoke(prompt)
        
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

        return {
            "answer": response.content,
            "sources": sources_summary
        }