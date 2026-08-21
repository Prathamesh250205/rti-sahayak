"""POST /api/ask - standalone Q&A over the RTI Act, 2005.

Answers ONLY from retrieved corpus text - see agent/qa.py's module
docstring for why a retrieval-distance guard on the question itself is the
right check here, unlike for drafting.
"""
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import llm.client as llm_client
from agent.qa import answer_question
from web import state as web_state
from web.rate_limit import is_rate_limited
from web.schemas import AskRequest, AskResponse, ChunkOut, ClauseOut

router = APIRouter()


@router.post("/api/ask", response_model=AskResponse)
def ask_question(req: AskRequest, request: Request):
    t0 = time.perf_counter()

    # Shares is_rate_limited()'s counter with /api/draft rather than
    # tracking a separate budget - both ultimately spend the same Groq/
    # Gemini quota, so the protection has to be on total requests per IP,
    # not per endpoint.
    client_ip = request.client.host if request.client else "unknown"
    if is_rate_limited(client_ip):
        return JSONResponse(
            status_code=429,
            content={"error": "Too many requests have come from this network in a short time. Please wait a few minutes and try again."},
        )

    if not web_state.ready:
        return AskResponse(
            answer="",
            citations=[],
            chunks=[],
            warnings=["The RTI Act knowledge base is still warming up. Please try again in a few seconds."],
            status="warming_up",
            meta={},
        )

    question = (req.question or "").strip()
    if not question:
        return JSONResponse(status_code=422, content={"detail": "A question is required."})

    result = answer_question(question)

    if result.status == "insufficient_grounding":
        return AskResponse(answer="", citations=[], chunks=[], warnings=[], status="insufficient_grounding", meta={})

    if result.status == "error":
        return JSONResponse(status_code=500, content={"error": "Could not generate an answer. Please try again."})

    latency_ms = int((time.perf_counter() - t0) * 1000)
    return AskResponse(
        answer=result.answer,
        citations=[ClauseOut(text=c["text"], section=c["section"], chunk_index=c["chunk_index"]) for c in result.citations],
        chunks=[ChunkOut(text=c.text, section=c.section, page=c.page, source=c.source, distance=c.distance) for c in result.chunks],
        warnings=[],
        status="ok",
        meta={"provider": llm_client.LAST_PROVIDER_USED, "latency_ms": latency_ms},
    )
