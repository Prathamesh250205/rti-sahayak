"""GET /api/system - read-only operational telemetry.

Every value is measured directly from the running process at request time
(the LLM provider config, the live Chroma collection, the retrieval
threshold actually in force, the startup warm-up duration, and the most
recent /api/draft call) - nothing here is estimated, sampled, or hardcoded.
Backs web/templates/partials/telemetry_modal.html, which is the honest
subset of design/stitch_rti_sahayak_ai_assistant/system_telemetry_modal -
that source screen also shows a "Citation Accuracy" percentage, a "Grounded
Answers" percentage, a per-section retrieval-score bar chart, and a
fabricated log stream (referencing a reranking service, Cohere Rerank v3,
this app has never used). None of those have a real number behind them in
this codebase, so none of them are represented here.
"""
import os

from fastapi import APIRouter

import llm.client as llm_client
from rag.retriever import MAX_RELEVANT_DISTANCE, _get_collection
from web import state as web_state

router = APIRouter()

_API_KEY_ENV = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
_MODEL_BY_PROVIDER = {
    "gemini": llm_client.GEMINI_MODEL,
    "groq": llm_client.GROQ_MODEL,
    "anthropic": llm_client.ANTHROPIC_MODEL,
}


@router.get("/api/system")
def system_status():
    # Gate 13: PROVIDER_CHAIN can now have 3 hops (or a fully custom order -
    # see LLM_PROVIDER_CHAIN), not a fixed groq/gemini pair. "fallback" here
    # stays the immediate next hop after primary, for the existing telemetry
    # UI's one-line note; "chain" carries the complete, correctly-ordered
    # picture for anything that wants it.
    chain = [
        {
            "provider": p,
            "model": _MODEL_BY_PROVIDER.get(p),
            "configured": bool(os.getenv(_API_KEY_ENV[p])),
        }
        for p in llm_client.PROVIDER_CHAIN
    ]
    fallback = llm_client.PROVIDER_CHAIN[1] if len(llm_client.PROVIDER_CHAIN) > 1 else None
    model = _MODEL_BY_PROVIDER.get(llm_client.PROVIDER)

    collection = _get_collection()
    result = collection.get(include=["metadatas"])
    metadatas = result["metadatas"]
    # Neither "Preamble" (real, citable front matter, but not a numbered
    # section - see rag/ingest.py's PREAMBLE_ANCHOR) nor "unknown" (should
    # be unreachable post-Preamble-fix, kept here defensively) count as a
    # numbered Act section - excluded so this counts what the tile actually
    # claims to count: distinct numbered RTI Act sections present in the
    # corpus.
    real_sections = set(
        m.get("section") for m in metadatas if m.get("section") not in ("unknown", "Preamble")
    )

    return {
        "provider": {
            "primary": llm_client.PROVIDER,
            "model": model,
            "fallback": fallback,
            "fallback_configured": bool(os.getenv(_API_KEY_ENV[fallback])) if fallback else False,
            "chain": chain,
        },
        "chunks_indexed": len(metadatas),
        "sections_indexed": len(real_sections),
        "max_relevant_distance": MAX_RELEVANT_DISTANCE,
        "warm_up_seconds": web_state.warm_up_seconds,
        "last_request": web_state.last_request,
    }
