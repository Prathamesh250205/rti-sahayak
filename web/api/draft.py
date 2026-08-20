"""POST /api/draft - one-shot, stateless wrapper around the existing
agent.intake / agent.drafter pipeline (the same pipeline app.py drives
turn-by-turn in the Streamlit UI). This endpoint takes all fields in a
single request instead: no session store, no agent.intake.process_reply.
"""
import io
import time
from dataclasses import asdict

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

import llm.client as llm_client
from agent.drafter import compose_letter, gather_grounding, understand_request
from agent.intake import IntakeState
from export.pdf_writer import build_pdf
from rag.retriever import MAX_RELEVANT_DISTANCE, retrieve
from web import state as web_state
from web.schemas import ChunkOut, ClauseOut, DraftRequest, DraftResponse, PdfRequest

router = APIRouter()

# How many chunks to pull when checking whether the Act's text actually
# covers the citizen's own topic (see the insufficient_grounding guard
# below) - separate from agent.drafter.gather_grounding(), which always
# retrieves the same fixed procedural queries (filing manner, response
# timeline) regardless of topic and so can't detect an off-topic request.
TOPIC_CHECK_TOP_K = 5


@router.post("/api/draft", response_model=DraftResponse)
def create_draft(req: DraftRequest):
    t0 = time.perf_counter()
    try:
        # Anti-hallucination guard: if nothing retrieved for the citizen's own
        # problem_description clears the relevance threshold, the Act's text
        # doesn't confidently cover this request - refuse to draft a letter
        # rather than have the LLM improvise information_sought/authority for
        # a topic (e.g. income tax filing) the corpus says nothing about.
        # Uses rag.retriever.MAX_RELEVANT_DISTANCE directly rather than a
        # second hardcoded threshold, so the two can't drift out of sync.
        topic_chunks = retrieve(req.problem_description, top_k=TOPIC_CHECK_TOP_K)
        best_distance = min((c.distance for c in topic_chunks), default=None)

        if not any(c.distance < MAX_RELEVANT_DISTANCE for c in topic_chunks):
            latency_ms = int((time.perf_counter() - t0) * 1000)
            web_state.last_request = {
                "latency_ms": latency_ms,
                "chunks_used": 0,
                "best_distance": best_distance,
            }
            return DraftResponse(
                application_text="",
                department_guess="",
                information_sought=[],
                chunks=[],
                clauses=[],
                warnings=[],
                status="insufficient_grounding",
                meta={
                    "provider": None,
                    "latency_ms": latency_ms,
                    "chunks_used": 0,
                },
            )

        # agent.intake.IntakeState.slots keys, verbatim from
        # agent/intake.py's REQUIRED_FIELDS (the dict missing_fields() reads):
        # "full_name", "address", "locality", "timeframe". Only set keys we
        # actually have a value for - _format_letter()'s slots.get(key, default)
        # fallback text only kicks in when the key is absent, not when it's "".
        # "pio" is not in REQUIRED_FIELDS (optional, not asked during the
        # Streamlit intake flow) - set the same way, just never required.
        state = IntakeState(problem_description=req.problem_description)
        state.slots["full_name"] = req.full_name
        state.slots["address"] = req.address
        if req.locality:
            state.slots["locality"] = req.locality
        if req.timeframe:
            state.slots["timeframe"] = req.timeframe
        if req.pio:
            state.slots["pio"] = req.pio

        information_sought, likely_authority = understand_request(
            req.problem_description,
            locality=req.locality or "",
            timeframe=req.timeframe or "",
            user_supplied_authority=req.public_authority or "",
        )
        chunks = gather_grounding()
        result = compose_letter(state, information_sought, likely_authority, chunks)
        result_dict = asdict(result)

        latency_ms = int((time.perf_counter() - t0) * 1000)
        web_state.last_request = {
            "latency_ms": latency_ms,
            "chunks_used": len(result_dict["grounding_chunks"]),
            "best_distance": best_distance,
        }
        return DraftResponse(
            application_text=result_dict["application_text"],
            department_guess=result_dict["department_guess"],
            information_sought=result_dict["information_sought"],
            chunks=[ChunkOut(**c) for c in result_dict["grounding_chunks"]],
            clauses=[ClauseOut(**c) for c in result_dict["clauses"]],
            warnings=result_dict["warnings"],
            status="ok",
            meta={
                "provider": llm_client.LAST_PROVIDER_USED,
                "latency_ms": latency_ms,
                "chunks_used": len(result_dict["grounding_chunks"]),
            },
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/api/draft/pdf")
def download_pdf(req: PdfRequest):
    try:
        pdf_bytes = build_pdf(req.application_text)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="RTI-Application.pdf"'},
    )
