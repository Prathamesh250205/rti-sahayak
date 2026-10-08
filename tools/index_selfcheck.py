"""Self-check for rag/retriever.py's numpy index (no LLM, no network).

Fails if the embedder drifts from the stored vectors, the distance scale
changes (MAX_RELEVANT_DISTANCE is tuned to chromadb's "l2" value = 1 - cosine),
or retrieval stops finding the obvious section. Run: python -m tools.index_selfcheck
"""
import numpy as np

from rag.retriever import MAX_RELEVANT_DISTANCE, _Embedder, _get_collection, retrieve


def main():
    idx = _get_collection()
    assert idx.count() == 83, idx.count()

    # Query-time embedder reproduces what ingest stored.
    assert np.allclose(_Embedder()(idx.documents[:5]), idx.embeddings[:5], atol=1e-5)

    # Distance scale: a chunk against its own stored vector is 0, and values sit
    # on chromadb's 0-2 scale (1 - cosine), not squared L2's 0-4.
    r = idx.query([idx.documents[0]], n_results=83)
    assert r["ids"][0][0] == idx.ids[0] and r["distances"][0][0] < 1e-4
    assert max(r["distances"][0]) <= 2.0

    sections = [c.section for c in retrieve("How many days does a PIO have to reply to an RTI application?")]
    assert "Section 7" in sections, sections
    assert all(c.distance <= MAX_RELEVANT_DISTANCE for c in retrieve("first appeal against a PIO decision"))
    assert retrieve("write me a poem about cricket") == []

    s7 = idx.get(where={"section": "Section 7"})
    assert s7["documents"] and all(m["section"] == "Section 7" for m in s7["metadatas"])
    print("index self-check: all passed")


if __name__ == "__main__":
    main()
