import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.messages import SystemMessage, HumanMessage

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
        # RELEVANCE_THRESHOLD = 0.5

        if filter_source:
            docs_scores = self.db.similarity_search_with_relevance_scores(
                question,
                k=6,
                filter={"source": filter_source}
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

        context_blocks = []
            
        # Format context with chunk details
        context_blocks = []
        for i, doc in enumerate(docs, start=1):
            source_name = doc.metadata.get("source", "Unknown")
            page_num = doc.metadata.get("page", "N/A")
            context_blocks.append(
                f"[Excerpt {i} | Source: {source_name} | Page: {page_num}]\n{doc.page_content}"
            )

        # context = "\n\n---\n\n".join(context_blocks)    

        context = "\n\n".join(
            doc.page_content for doc in docs
        )
        
        system_prompt = """
        You are a professional document assistant.

        Rules:
        - Answer only using the provided information.
        - Never mention documents, sources, context, excerpts, page numbers, or file names.
        - Write naturally and professionally.
        - Do not use markdown bullet style with '*' characters.
        - Use proper spacing and formatting for readability.

        Formatting Guidelines:

        1. If information belongs to categories, present it in sections.

        Example:

        **Languages**
        - Python
        - SQL
        - JavaScript

        **Databases**
        - MySQL
        - MongoDB

        **Cloud**
        - AWS

        2. If the answer contains attributes and values, use:

        **Name:** John Doe
        **Email:** john@example.com
        **Role:** Data Engineer

        3. If the user asks multiple questions, answer each separately.

        Example:

        **Total Projects:** 3

        **Project Explanation**

        Dermalens is a skin cancer detection system that uses deep learning to classify skin lesions as benign or malignant.

        4. For summaries:
        - Use short paragraphs.
        - Organize information logically.
        - Use headings when appropriate.

        5. For lists:
        - Use numbered lists when order matters.
        - Use dash (-) lists when order does not matter.

        6. If information is missing, state that clearly and briefly without guessing.

        Always prefer clean, structured, professional formatting over long unformatted paragraphs.
        """

        human_prompt = f"""Context:
                {context}

        Question:
        {question}"""

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
        
        print(response.content)

        return {
            "answer": response.content,
            "sources": sources_summary
        }

        # prompt = f"""
        # You are a helpful assistant that answers questions using only the context provided below.

        # Guidelines:
        # - Answer naturally, as if you already know this information — never refer to "the document," "the context," "excerpts," "sources," page numbers, or file names.
        # - Be thorough and clear. Where useful, explain concepts, give examples, or restructure information (e.g. as steps or a short list) rather than just copying phrasing from the context.
        # - If the answer isn't in the context, say so briefly and naturally — don't guess.
        # - Do not reference where the information came from in any way.
        
        
        # Context:
        # {context}

        # Question:
        # {question}

        # Answer:
        # """

        # response = self.llm.invoke(prompt)
        
        # # Collect unique sources
        # unique_sources = {}
        # for doc in docs:
        #     src = doc.metadata.get("source", "Unknown")
        #     page = doc.metadata.get("page", None)
        #     if src not in unique_sources:
        #         unique_sources[src] = set()
        #     if page is not None:
        #         unique_sources[src].add(page)

        # sources_summary = [
        #     {
        #         "source": src,
        #         "pages": sorted(list(pages)) if pages else "N/A"
        #     }
        #     for src, pages in unique_sources.items()
        # ]

        # return {
        #     "answer": response.content,
        #     "sources": sources_summary
        # }