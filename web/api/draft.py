"""POST /api/draft - one-shot, stateless wrapper around the existing
agent.intake / agent.drafter pipeline (the same pipeline app.py drives
turn-by-turn in the Streamlit UI). This endpoint takes all fields in a
single request instead: no session store, no agent.intake.process_reply.

Two independent checks gate a draft, deliberately kept separate because
they answer different questions and fail in different ways:

  CHECK A (procedural grounding, deterministic): does the corpus actually
  contain the procedural text that backs the Section 6/7 clauses and the
  citation chips? gather_grounding()'s two fixed queries always retrieve
  well against a real, populated corpus - this only fails if Chroma is
  empty or broken (e.g. a deploy that skipped ingestion), never because of
  anything about the specific request. Kept as the "insufficient_grounding"
  status/screen, now scoped to exactly this failure mode.

  CHECK B (scope, LLM classification): is this genuinely a request for
  records held by an Indian public authority? Semantic similarity between
  a citizen's grievance and the Act's own text is close to meaningless -
  the Act is purely procedural and never mentions ration cards, roads, or
  pensions by name - so this used to be answered (badly) by a retrieval-
  distance check on the citizen's own text, which produced both false
  refusals (legitimate requests with no vocabulary overlap) and
  meaningless false positives (an unrelated grievance scoring under
  threshold against an unrelated section by coincidence). It's an explicit
  model verdict now - see agent.drafter.UnderstandResult.in_scope - not
  inferred from retrieval distance or from information_sought coming back
  empty, which would conflate a genuine "not a records request" answer
  with a provider hiccup.
"""
import io
import sys
import time
from dataclasses import asdict

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

import llm.client as llm_client
from agent.drafter import compose_letter, gather_grounding, understand_request
from agent.intake import IntakeState
from export.pdf_writer import build_pdf
from web import state as web_state
from web.schemas import ChunkOut, ClauseOut, DraftRequest, DraftResponse, PdfRequest

router = APIRouter()


@router.post("/api/draft", response_model=DraftResponse)
def create_draft(req: DraftRequest):
    t0 = time.perf_counter()

    # The retriever's embedding model loads in a background task (see
    # web/main.py's lifespan) so the server can bind its port immediately.
    # A request landing before that finishes would otherwise race an
    # unloaded collection - tell the client plainly instead.
    if not web_state.ready:
        return DraftResponse(
            application_text="",
            department_guess="",
            information_sought=[],
            chunks=[],
            clauses=[],
            warnings=["The RTI Act knowledge base is still warming up. Please try again in a few seconds."],
            status="warming_up",
            meta={"provider": None, "latency_ms": 0, "chunks_used": 0},
        )

    try:
        # CHECK A - procedural grounding. Runs first and needs no LLM call,
        # so a broken deploy is caught cheaply, before anything else.
        chunks = gather_grounding()
        best_distance = min((c.distance for c in chunks), default=None)

        if not chunks:
            print(
                "[draft] CHECK A (procedural grounding) found zero chunks - the Chroma "
                "collection is empty or broken. This is a corpus/deploy failure, not a "
                "verdict about this specific request.",
                file=sys.stderr,
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)
            web_state.last_request = {"latency_ms": latency_ms, "chunks_used": 0, "best_distance": None}
            return DraftResponse(
                application_text="",
                department_guess="",
                information_sought=[],
                chunks=[],
                clauses=[],
                warnings=[],
                status="insufficient_grounding",
                meta={"provider": None, "latency_ms": latency_ms, "chunks_used": 0},
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
        if req.phone:
            state.slots["phone"] = req.phone
        if req.email:
            state.slots["email"] = req.email
        if req.is_bpl:
            state.slots["is_bpl"] = "true"

        # CHECK B - scope. See module docstring.
        understanding = understand_request(
            req.problem_description,
            locality=req.locality or "",
            timeframe=req.timeframe or "",
            user_supplied_authority=req.public_authority or "",
        )
        information_sought, likely_authority = understanding

        if understanding.in_scope is False:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            web_state.last_request = {"latency_ms": latency_ms, "chunks_used": 0, "best_distance": best_distance}
            return DraftResponse(
                application_text="",
                department_guess="",
                information_sought=[],
                chunks=[],
                clauses=[],
                warnings=[],
                status="out_of_scope",
                meta={
                    "provider": llm_client.LAST_PROVIDER_USED,
                    "latency_ms": latency_ms,
                    "chunks_used": 0,
                    "scope_reason": understanding.scope_reason,
                },
            )

        extra_warnings = []
        if understanding.in_scope is None:
            # Fail-open: CHECK A already holds, and a mysterious refusal
            # during a live demo is worse than a flagged draft - see
            # agent/drafter.py's UnderstandResult.in_scope docs. The
            # citizen still sees this plainly rather than a silent gap.
            extra_warnings.append(
                "Automated scope screening was unavailable for this request (the classification "
                "step failed) - this draft was produced anyway. Please double-check that this is "
                "genuinely a request for a specific record before submitting."
            )

        letter = compose_letter(state, information_sought, likely_authority, chunks)
        result_dict = asdict(letter)

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
            warnings=extra_warnings + result_dict["warnings"],
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
