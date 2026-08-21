"""Query interface over the Chroma RTI corpus collection.

Every result carries its section/page metadata so callers can cite sources
and can tell when nothing relevant was found, instead of improvising.
"""
import os
from dataclasses import dataclass

import chromadb
import streamlit as st
from chromadb.utils import embedding_functions

CHROMA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "chroma")
# Must match rag/ingest.py's ONNX_CACHE_DIR override exactly - see the
# comment there for why this isn't chromadb's ~/.cache default.
ONNX_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "onnx_model_cache")
COLLECTION_NAME = "rti_corpus"

# Chroma's default distance is squared L2 over normalized MiniLM embeddings.
# Re-measured after switching rag/ingest.py from 500-word sliding-window
# chunks to section-boundary chunks (~975 chars mean, vs ~3128 before):
# smaller, more topically focused chunks pull genuine RTI-procedure queries
# in closer (best matches ~0.21-0.73) but also pull the *best* off-topic
# match in closer too (~0.78+, down from ~0.95+ under the old chunking) - a
# stray sentence in a small chunk has a better chance of superficially
# resembling an unrelated query than the same sentence buried in a 3000-char
# chunk did. The old 0.8 cutoff sat above the new off-topic floor (0.78),
# so it would wrongly admit clearly off-topic queries; 0.75 sits back in the
# gap between the two clusters. Chunks above this cutoff are not relevant.
MAX_RELEVANT_DISTANCE = 0.75

class RetrieverError(RuntimeError):
    """Raised when the Chroma collection is missing or unreadable."""


@dataclass
class RetrievedChunk:
    text: str
    section: str
    page: int
    source: str
    distance: float


@st.cache_resource(show_spinner="Loading the RTI Act knowledge base (one-time, ~20s)...")
def _get_collection():
    """Load the embedding model + Chroma collection once per server process.

    This is the single biggest latency cost in the app (loading the
    embedding model from disk) - st.cache_resource means every session
    after the first one gets it for free, and every rerun within a session
    is a cache hit rather than a re-load.

    ONNX runtime, not sentence-transformers/torch - same model
    (all-MiniLM-L6-v2) and output vectors, but without a ~500MB PyTorch
    runtime just to run inference. Must match rag/ingest.py's embedding
    function exactly, or these query-time vectors won't be comparable to
    what's actually stored in the collection.
    """
    embedding_functions.ONNXMiniLM_L6_V2.DOWNLOAD_PATH = ONNX_CACHE_DIR
    embed_fn = embedding_functions.ONNXMiniLM_L6_V2()
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME not in existing:
        raise RetrieverError(
            "RTI corpus is not ingested yet. Run `python -m rag.ingest` first."
        )
    return client.get_collection(COLLECTION_NAME, embedding_function=embed_fn)


def warm_up() -> None:
    """Force the embedding model to actually load now rather than on first use.

    Call this once at app startup so the one-time model-load cost (~20s,
    or longer on a cold cache - see rag/ingest.py) happens behind a startup
    spinner instead of interrupting a live conversation the first time a
    user reaches the drafting step.

    ONNXMiniLM_L6_V2 loads its model lazily inside __call__, not in
    __init__ or when the collection object is obtained - _get_collection()
    alone does not touch it. A throwaway query forces the same __call__
    path retrieve() uses, so this actually pays the load cost here instead
    of silently deferring it to the first real request.
    """
    collection = _get_collection()
    collection.query(query_texts=["warm up"], n_results=1)


def retrieve(query: str, top_k: int = 4) -> list[RetrievedChunk]:
    """Return up to top_k relevant chunks for query, most relevant first.

    Returns an empty list if nothing in the corpus is relevant enough —
    callers must treat that as "no grounding available", not fall back to
    the model's own knowledge.
    """
    collection = _get_collection()
    result = collection.query(query_texts=[query], n_results=top_k)

    chunks = []
    documents = result["documents"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]

    for text, meta, distance in zip(documents, metadatas, distances):
        if distance > MAX_RELEVANT_DISTANCE:
            continue
        chunks.append(
            RetrievedChunk(
                text=text,
                section=meta["section"],
                page=meta["page"],
                source=meta["source"],
                distance=distance,
            )
        )
    return chunks


def format_context(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks as a citation-labeled block for an LLM prompt."""
    if not chunks:
        return ""
    parts = []
    for chunk in chunks:
        label = chunk.section if chunk.section != "unknown" else f"{chunk.source} p.{chunk.page}"
        parts.append(f"[{label}]\n{chunk.text}")
    return "\n\n".join(parts)
