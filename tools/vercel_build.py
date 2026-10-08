"""Vercel build command (see vercel.json): fetch the embedding model.

The search index itself (data/index/) is committed, so deploys don't re-run
ingestion and don't need the PDF reader. The model (~90 MB) isn't committed;
it's downloaded here, checked against its sha256, and unpacked into the
bundle. Run: python -m tools.vercel_build
"""
from rag.retriever import MODEL_DIR, ensure_model

if __name__ == "__main__":
    ensure_model()
    print(f"[build] embedding model ready in {MODEL_DIR}")
