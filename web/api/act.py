"""GET endpoints for browsing the RTI Act corpus - read directly from the
same corpus index rag/retriever.py uses (via its _get_collection()),
without modifying that module. Nothing here is hardcoded: every section name,
chunk count, and piece of text comes straight out of the collection that
rag/ingest.py populated from the actual corpus PDF(s).
"""
import functools
import json
import os
import re

from fastapi import APIRouter, HTTPException

from rag.retriever import INDEX_DIR, RetrieverError, _get_collection, retrieve

router = APIRouter()


@functools.cache
def _translations() -> dict:
    """Unofficial Hindi/Marathi translations of each chunk, by chunk id
    (tools/translate_act.py). The official Hindi/Marathi PDFs have no
    extractable text, so these are what the site can show; the page labels
    them and keeps the English one click away. Missing file = English only."""
    try:
        with open(os.path.join(INDEX_DIR, "translations.json"), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _localise(chunk_id: str, text: str, lang: str) -> tuple[str, bool]:
    translated = _translations().get(lang, {}).get(chunk_id)
    return (translated, True) if translated else (text, False)


@functools.cache
def _id_by_text() -> dict:
    # search results come from retrieve(), which returns text but not ids
    result = _get_collection().get(include=["documents"])
    return dict(zip(result["documents"], result["ids"]))


def chunk_translations(text: str) -> dict:
    """{lang: translation} for an indexed chunk's text (Ask/Draft source cards)."""
    chunk_id = _id_by_text().get(text)
    return {lang: by_id[chunk_id] for lang, by_id in _translations().items() if chunk_id in by_id}

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
def get_section(section: str, lang: str = "en"):
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

    chunks = []
    for chunk_id, doc, meta in zip(result["ids"], documents, metadatas):
        text, translated = _localise(chunk_id, doc, lang)
        chunks.append({"text": text, "translated": translated, "page": meta.get("page"), "source": meta.get("source")})
    chunks.sort(key=lambda c: c["page"] if isinstance(c["page"], int) else 0)

    return {"section": section, "chunks": chunks}


@router.get("/api/act/search")
def search_act(q: str = "", lang: str = "en"):
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required.")

    try:
        chunks = retrieve(q, top_k=8)
    except RetrieverError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "query": q,
        "results": [
            dict(zip(("text", "translated"), _localise(_id_by_text().get(c.text, ""), c.text, lang)),
                 section=c.section, page=c.page, source=c.source, distance=c.distance)
            for c in chunks
        ],
    }
