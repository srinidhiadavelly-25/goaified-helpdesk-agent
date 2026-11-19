"""
Stage 2 - Build the vector database.

Run once (and again whenever you add or change a document in data/):
    python ingest.py
"""
from src import config, rag


def main() -> None:
    docs = rag.load_documents()
    print(f"Loaded {len(docs)} documents from {config.DATA_DIR}")
    for d in docs:
        print(f"  - [{d.metadata['category'].upper()}] {d.metadata['source']}")
    n = rag.build_index()
    print(f"\nStored {n} chunks in ChromaDB at {config.CHROMA_DIR}")

    print("\nQuick retrieval check: 'How many annual leave days do I get?'")
    for doc in rag.retrieve("How many annual leave days do I get?", k=2):
        print(f"  -> {doc.metadata['source']}: {doc.page_content[:90]!r}...")


if __name__ == "__main__":
    main()
