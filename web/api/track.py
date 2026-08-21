"""GET /api/track/deadline-rules - the Act-grounded statutory deadline rules
/track computes filings against.

No LLM call - pure retrieval against the corpus (see agent/deadlines.py),
so this is free to fetch on every /track page load without spending any
provider quota, same as web/api/act.py's browse endpoints. Not rate limited
for the same reason those aren't.
"""
from fastapi import APIRouter, HTTPException

from agent.deadlines import gather_deadline_rules
from rag.retriever import RetrieverError
from web.schemas import ChunkOut, DeadlineRuleOut, TrackRulesResponse

router = APIRouter()


@router.get("/api/track/deadline-rules", response_model=TrackRulesResponse)
def deadline_rules():
    try:
        rules, chunks, warnings = gather_deadline_rules()
    except RetrieverError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return TrackRulesResponse(
        rules=[
            DeadlineRuleOut(
                id=r.id,
                label=r.label,
                section=r.section,
                chunk_index=r.chunk_index,
                offset_days=r.offset_days,
                offset_hours=r.offset_hours,
                anchor=r.anchor,
                applies_when=r.applies_when,
            )
            for r in rules
        ],
        chunks=[ChunkOut(text=c.text, section=c.section, page=c.page, source=c.source, distance=c.distance) for c in chunks],
        warnings=warnings,
        status="ok",
    )
