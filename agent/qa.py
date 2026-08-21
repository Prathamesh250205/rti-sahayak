"""Answer standalone questions about the RTI Act, 2005 - grounded ONLY in
retrieved corpus text, never the model's own general knowledge.

This is a genuinely different question from agent.drafter's grounding
design: drafting a letter doesn't need the Act's text to resemble the
citizen's grievance (the Act covers almost any topic procedurally, see
agent/drafter.py's module docstring), but *answering a question about the
Act* does need the Act's own text to actually contain something relevant -
if nothing retrieves, there is genuinely nothing to answer from. A
retrieval-distance guard on the question itself is therefore the right
tool here, not the wrong one it was for drafting.
"""
import re
import sys
from dataclasses import dataclass, field

from llm.client import LLMError, generate, parse_json_object
from rag.retriever import RetrievedChunk, retrieve

# Matches an inline citation marker like "[2]" that the model places directly
# in its own answer text (see answer_question's prompt).
_MARKER_RE = re.compile(r"\[(\d+)\]")

# Raised from 5: a real user question ("After how many days does a PIO
# have to respond?") retrieved the actual Section 7 answer at rank 8, well
# inside the 0.75 distance threshold but outside a top-5 cutoff - the
# question got an honest "the excerpts don't cover this" instead of the
# answer that was sitting right there. Same root cause and same fix as
# Gate 13's deadline-endpoint top_k bump. Cost: roughly doubles this
# endpoint's context tokens (~1200 -> ~2400 at this corpus's ~243
# tokens/chunk average) - acceptable given answer_question()'s prompt
# already instructs the model to cite only what it finds and note gaps
# rather than blend indiscriminately, so extra lower-ranked chunks are a
# token-cost risk, not a fabrication one.
ANSWER_TOP_K = 10
ANSWER_MAX_TOKENS = 800


@dataclass
class QAResult:
    # "ok" | "insufficient_grounding" (nothing retrieved - a real, honest
    # refusal) | "error" (LLM call failed or returned something unusable -
    # a service problem, never conflated with a genuine refusal).
    status: str
    answer: str = ""
    citations: list[dict] = field(default_factory=list)
    chunks: list[RetrievedChunk] = field(default_factory=list)


def answer_question(question: str) -> QAResult:
    chunks = retrieve(question, top_k=ANSWER_TOP_K)
    if not chunks:
        return QAResult(status="insufficient_grounding")

    context = "\n\n".join(f"[{i}] ({c.section}) {c.text}" for i, c in enumerate(chunks))
    prompt = (
        "Answer the citizen's question about the Right to Information Act, 2005 using "
        "ONLY the numbered excerpts below. Do not use any outside knowledge, even if you "
        "know the answer - if the excerpts don't fully answer the question, say what they "
        "do cover and note what's missing rather than filling the gap yourself.\n\n"
        f"Excerpts:\n{context}\n\n"
        f'Question: "{question}"\n\n'
        "Immediately after every factual claim, insert the excerpt number it came from "
        "in square brackets, e.g. 'within thirty days [0]'. Use the number exactly as "
        "given above - do not renumber. If a claim draws on more than one excerpt, cite "
        "each, e.g. 'as amended [1][3]'.\n\n"
        'Respond with ONLY a JSON object: {"answer": "<answer text with inline [N] '
        'markers>"}'
    )

    def _call() -> str:
        return generate(
            prompt,
            system="You answer questions about Indian law using only the text you are given.",
            max_tokens=ANSWER_MAX_TOKENS,
        )

    try:
        response = _call()
    except LLMError as e:
        # Gate 12d: this is a genuine "both providers failed" case (generate()
        # already retries the fallback internally and logs that attempt) -
        # log it explicitly too so a total-failure Q&A error is as visible in
        # the log as the 500 it produces is to the client.
        print(f"[qa] answer_question: LLM call failed: {e}", file=sys.stderr)
        return QAResult(status="error")

    parsed = parse_json_object(response)

    # Same retry discipline as agent.drafter.understand_request: a response
    # that failed to parse but wasn't empty is a completion cut short
    # mid-JSON, worth one retry. A genuinely empty response is left alone -
    # retrying would risk masking a real provider failure behind a second
    # silent attempt instead of surfacing it as the honest "error" it is.
    if not parsed and response.strip():
        try:
            response = _call()
            parsed = parse_json_object(response)
        except LLMError as e:
            print(f"[qa] answer_question: retry after truncated response also failed: {e}", file=sys.stderr)
            # fall through to the error path below

    answer = str(parsed.get("answer") or "").strip() if parsed else ""
    if not answer:
        return QAResult(status="error")

    # Citations are read directly off markers the model placed in its own
    # answer text (see the prompt above), rather than a separate self-quoted
    # "text" field - a model asked to quote itself verbatim reliably
    # paraphrases (e.g. "receipt" vs "the receipt"), which silently drops
    # every citation under the old verbatim-match check. A marker like "[2]"
    # is, by construction, always present in the text it was just found in,
    # so there is nothing to verify beyond the excerpt number being real.
    citations = []
    for match in _MARKER_RE.finditer(answer):
        idx = int(match.group(1))
        if 0 <= idx < len(chunks):
            citations.append({"text": match.group(0), "section": chunks[idx].section, "chunk_index": idx})

    return QAResult(status="ok", answer=answer, citations=citations, chunks=chunks)
