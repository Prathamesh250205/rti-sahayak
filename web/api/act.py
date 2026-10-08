"""GET endpoints for browsing the RTI Act corpus - read directly from the
same corpus index rag/retriever.py uses (via its _get_collection()),
without modifying that module. Nothing here is hardcoded: every section name,
chunk count, and piece of text comes straight out of the collection that
rag/ingest.py populated from the actual corpus PDF(s).
"""
import re

from fastapi import APIRouter, HTTPException

from rag.retriever import RetrieverError, _get_collection, retrieve

router = APIRouter()

# rag/ingest.py ids chunks "{filename}-c{chunk_id}", where chunk_id increments
# in the order chunks were sliced out of the document - i.e. true reading
# order, which page/section metadata alone can't give us (a section can span
# several pages, and several sections can share one page). Used only to order
# the /sections listing; unmatched ids just sort last within their source.
_CHUNK_ID_RE = re.compile(r"-c(\d+)$")


def _chunk_order_key(chunk_id: str, source: str, page) -> tuple:
    match = _CHUNK_ID_RE.search(chunk_id)
    if match:
        return (source, 0, int(match.group(1)))
    return (source, 1, page if isinstance(page, int) else 0)


@router.get("/api/act/sections")
def list_sections():
    """Distinct sections in the collection, each with its chunk count, in
    document order where determinable (see _chunk_order_key above)."""
    try:
        collection = _get_collection()
    except RetrieverError as e:
        raise HTTPException(status_code=503, detail=str(e))

    result = collection.get(include=["metadatas"])
    ids = result["ids"]
    metadatas = result["metadatas"]

    sections: dict[str, dict] = {}
    for chunk_id, meta in zip(ids, metadatas):
        section = meta.get("section") or "unknown"
        source = meta.get("source", "")
        page = meta.get("page")
        order_key = _chunk_order_key(chunk_id, source, page)

        entry = sections.get(section)
        if entry is None:
            sections[section] = {"section": section, "chunk_count": 1, "_order_key": order_key}
        else:
            entry["chunk_count"] += 1
            if order_key < entry["_order_key"]:
                entry["_order_key"] = order_key

    ordered = sorted(sections.values(), key=lambda s: s["_order_key"])
    for s in ordered:
        del s["_order_key"]

    return {"sections": ordered, "total_chunks": len(ids)}


@router.get("/api/act/section/{section}")
def get_section(section: str):
    """All chunks tagged with `section`, ordered by page."""
    try:
        collection = _get_collection()
    except RetrieverError as e:
        raise HTTPException(status_code=503, detail=str(e))

    result = collection.get(where={"section": section}, include=["documents", "metadatas"])
    documents = result["documents"]
    metadatas = result["metadatas"]

    if not documents:
        raise HTTPException(status_code=404, detail=f"No chunks found for section {section!r}.")

    chunks = [
        {"text": doc, "page": meta.get("page"), "source": meta.get("source")}
        for doc, meta in zip(documents, metadatas)
    ]
    chunks.sort(key=lambda c: c["page"] if isinstance(c["page"], int) else 0)

    return {"section": section, "chunks": chunks}


@router.get("/api/act/search")
def search_act(q: str = ""):
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required.")

    try:
        chunks = retrieve(q, top_k=8)
    except RetrieverError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "query": q,
        "results": [
            {"text": c.text, "section": c.section, "page": c.page, "source": c.source, "distance": c.distance}
            for c in chunks
        ],
    }
