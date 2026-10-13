"""GET endpoints for browsing the RTI Act corpus. Nothing here is hardcoded:
every section name, chunk count, and piece of text comes straight out of the
index rag/ingest.py built from the actual corpus PDF(s).

Browsing reads only data/index/chunks.json - never the embedding model, which
takes 5-25s to load on a cold start (only /search needs it). Section data is
the same for everyone and changes only on deploy, so the CDN caches it.
"""
import functools
import json
import os
import re

from fastapi import APIRouter, HTTPException, Response

from rag.retriever import INDEX_DIR, RetrieverError, retrieve

router = APIRouter()
# Vercel's CDN keeps a copy per deployment (s-maxage), so most visitors are
# answered without the Python function starting at all.
CDN_CACHE = "public, max-age=300, s-maxage=86400, stale-while-revalidate=604800"


@functools.cache
def _chunks() -> list[tuple[str, str, dict]]:
    """(id, text, metadata) for every indexed chunk, from chunks.json."""
    try:
        with open(os.path.join(INDEX_DIR, "chunks.json"), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise RetrieverError("RTI corpus is not ingested yet. Run `python -m rag.ingest` first.")
    return list(zip(data["ids"], data["documents"], data["metadatas"]))


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
    return {text: chunk_id for chunk_id, text, _ in _chunks()}


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
def list_sections(response: Response):
    """Distinct sections in the collection, each with its chunk count, in
    document order where determinable (see _chunk_order_key above)."""
    try:
        chunks = _chunks()
    except RetrieverError as e:
        raise HTTPException(status_code=503, detail=str(e))

    sections: dict[str, dict] = {}
    for chunk_id, _, meta in chunks:
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

    response.headers["Cache-Control"] = CDN_CACHE
    return {"sections": ordered, "total_chunks": len(chunks)}


@router.get("/api/act/section/{section}")
def get_section(section: str, response: Response, lang: str = "en"):
    """All chunks tagged with `section`, ordered by page."""
    try:
        matching = [c for c in _chunks() if c[2].get("section") == section]
    except RetrieverError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not matching:
        raise HTTPException(status_code=404, detail=f"No chunks found for section {section!r}.")

    chunks = []
    for chunk_id, doc, meta in matching:
        text, translated = _localise(chunk_id, doc, lang)
        chunks.append({"text": text, "translated": translated, "page": meta.get("page"), "source": meta.get("source")})
    chunks.sort(key=lambda c: c["page"] if isinstance(c["page"], int) else 0)

    response.headers["Cache-Control"] = CDN_CACHE
    return {"section": section, "chunks": chunks}


@router.get("/api/act/all")
def get_all(response: Response, lang: str = "en"):
    """Every section's chunks in one response (~25 KB gzipped), so Browse
    opens sections from memory instead of a network trip per click."""
    sections = list_sections(Response())["sections"]
    response.headers["Cache-Control"] = CDN_CACHE
    return {"sections": sections,
            "chunks": {s["section"]: get_section(s["section"], Response(), lang)["chunks"] for s in sections}}


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
