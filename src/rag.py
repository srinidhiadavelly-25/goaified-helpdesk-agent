"""
RAG (Retrieval-Augmented Generation) module.

Pipeline:
    1. LOAD    - read every policy document in data/hr and data/it
    2. SPLIT   - cut each document into overlapping chunks (~800 characters)
    3. EMBED   - convert each chunk into a vector with Gemini embeddings
    4. STORE   - save the vectors + metadata in ChromaDB (on disk, ./chroma_db)
    5. RETRIEVE- at question time, embed the question and return the most
                 similar chunks, which the LLM then uses as its only source
                 of truth (this is what keeps answers grounded).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from pypdf import PdfReader

from src import config

SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}

_embeddings: Embeddings | None = None
_vectorstore: Chroma | None = None


# ---------------------------------------------------------------- embeddings
def get_embeddings() -> Embeddings:
    """Return one shared Gemini embeddings client."""
    global _embeddings
    if _embeddings is None:
        _embeddings = GoogleGenerativeAIEmbeddings(
            model=config.EMBEDDING_MODEL,
            google_api_key=config.GOOGLE_API_KEY,
        )
    return _embeddings


# ------------------------------------------------------------------- loading
def _read_file(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8")


def load_documents(data_dir: Path = config.DATA_DIR) -> list[Document]:
    """Load every supported file. The sub-folder name (hr / it) becomes the category."""
    docs: list[Document] = []
    for path in sorted(data_dir.rglob("*")):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        category = path.parent.name.lower()  # "hr" or "it"
        text = _read_file(path)
        title = next(
            (line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("# ")),
            path.stem.replace("_", " ").title(),
        )
        docs.append(
            Document(
                page_content=text,
                metadata={"source": path.name, "category": category, "title": title},
            )
        )
    return docs


# ----------------------------------------------------------------- splitting
def split_documents(docs: list[Document]) -> list[Document]:
    """
    Two-step split:
      a) by Markdown headings, so each chunk stays inside one policy section
      b) by size (800 chars, 120 overlap) so no chunk is too large to embed well
    The section heading is kept in metadata so we can cite it.
    """
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2")], strip_headers=False
    )
    size_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)

    chunks: list[Document] = []
    for doc in docs:
        sections = header_splitter.split_text(doc.page_content) if doc.metadata["source"].endswith(".md") else [doc]
        for section in sections:
            for piece in size_splitter.split_documents([section]):
                meta = {**doc.metadata}
                meta["section"] = section.metadata.get("h2", "") if hasattr(section, "metadata") else ""
                # Prefix the document title so every chunk carries its context
                content = piece.page_content
                if not content.startswith("# "):
                    content = f"[{doc.metadata['title']}]\n{content}"
                chunks.append(Document(page_content=content, metadata=meta))
    return chunks


# ------------------------------------------------------------------- storage
def build_index(data_dir: Path = config.DATA_DIR, reset: bool = True) -> int:
    """Create (or rebuild) the ChromaDB index. Returns the number of chunks stored."""
    global _vectorstore
    if reset and Path(config.CHROMA_DIR).exists():
        shutil.rmtree(config.CHROMA_DIR)
    _vectorstore = None

    chunks = split_documents(load_documents(data_dir))
    ids = [f"{c.metadata['source']}::{i}" for i, c in enumerate(chunks)]
    Chroma.from_documents(
        documents=chunks,
        embedding=get_embeddings(),
        ids=ids,
        collection_name=config.CHROMA_COLLECTION,
        persist_directory=config.CHROMA_DIR,
    )
    return len(chunks)


def get_vectorstore() -> Chroma:
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = Chroma(
            collection_name=config.CHROMA_COLLECTION,
            embedding_function=get_embeddings(),
            persist_directory=config.CHROMA_DIR,
        )
    return _vectorstore


# ----------------------------------------------------------------- retrieval
def retrieve(question: str, category: str | None = None, k: int = config.RETRIEVER_K) -> list[Document]:
    """
    Return the k most relevant chunks. If the agent already knows the question
    is HR or IT, we filter on that category so IT chunks never pollute HR answers.
    """
    store = get_vectorstore()
    search_filter = {"category": category} if category in ("hr", "it") else None
    results = store.similarity_search(question, k=k, filter=search_filter)
    if not results and search_filter:  # fall back to searching everything
        results = store.similarity_search(question, k=k)
    return results


def format_context(docs: list[Document]) -> str:
    """Turn retrieved chunks into a numbered context block for the prompt."""
    parts = []
    for i, d in enumerate(docs, start=1):
        parts.append(f"[Source {i}: {d.metadata.get('source')}]\n{d.page_content}")
    return "\n\n".join(parts)


def unique_sources(docs: list[Document]) -> list[str]:
    seen: list[str] = []
    for d in docs:
        label = d.metadata.get("title") or d.metadata.get("source")
        label = f"{label} ({d.metadata.get('source')})"
        if label not in seen:
            seen.append(label)
    return seen
