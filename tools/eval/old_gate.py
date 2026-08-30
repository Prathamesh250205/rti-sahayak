"""Faithful reconstruction of the pre-Gate-4/5 scope gate, as an
EVALUATION-ONLY code path for Gate E3's comparison. Never imported by the
live application (web/, agent/) - grep for "old_gate" outside tools/eval/
to confirm.

Reconstructed from git history, not memory. The removed logic, from
web/api/draft.py at commit ce1f53c^ (parent of "Fix front-matter grounding,
replace topic gate with LLM scope check, add corpus health guards"), was:

    topic_chunks = retrieve(req.problem_description, top_k=5)
    if not any(c.distance < MAX_RELEVANT_DISTANCE for c in topic_chunks):
        refuse()  # what was then called "insufficient_grounding"

rag/retriever.py's retrieve() and MAX_RELEVANT_DISTANCE are byte-for-byte
identical between that commit and today (diffed directly to confirm before
writing this file) - retrieve() already filters out anything beyond
MAX_RELEVANT_DISTANCE internally, so every chunk it returns already
satisfies distance < threshold. That makes the old gate's actual predicate
exactly: does retrieving the citizen's raw text at top_k=5 return anything
at all under the threshold?

Evaluated against today's live corpus (83 chunks, post Section-7 chunking
fix), not a historical replay of the 78-chunk corpus at the time this gate
was removed - deliberately, so the comparison isolates gate DESIGN as the
variable, not corpus state. Both gates in Gate E3 see identical data.
"""
from rag.retriever import RetrieverError, retrieve

OLD_GATE_TOP_K = 5


def old_gate_predict(query: str) -> tuple[bool, str]:
    """Returns (predicted_in_scope, reason). True if retrieving the
    citizen's own text directly returns at least one chunk under
    MAX_RELEVANT_DISTANCE; False if it returns none. No LLM call, no scope
    reasoning - purely retrieval distance on the citizen's own words,
    exactly as it worked before Gate 4-5.
    """
    try:
        chunks = retrieve(query, top_k=OLD_GATE_TOP_K)
    except RetrieverError as e:
        return False, f"RetrieverError: {e}"
    if chunks:
        best = min(c.distance for c in chunks)
        return True, f"{len(chunks)} chunk(s) under threshold, best distance={best:.4f} (top: {chunks[0].section})"
    return False, "no chunks retrieved under MAX_RELEVANT_DISTANCE for the citizen's own text"
