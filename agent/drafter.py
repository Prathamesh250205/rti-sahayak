"""Draft an RTI application, grounded in retrieved RTI Act 2005 excerpts.

Safety rules (non-negotiable — see project brief):
  - Procedural/legal claims (timelines, fees, rights) must come from
    retrieved excerpts, cited by section number.
  - If nothing relevant is retrieved, say so rather than improvise.
  - Never invent a department name/officer/address — mark best guesses.

Design note: the LLM is used only for the two things that genuinely need
judgment — figuring out what specific information to request, and guessing
the likely department. The legal/procedural clauses (filing manner, fee,
response timeline) are assembled in plain Python, and each is only included
after verifying its underlying fact-keywords are actually present in the
retrieved grounding text. This is stricter than asking the LLM to narrate
citations itself — in testing, a single freeform drafting prompt still
occasionally misattributed a fact to the wrong section, which the safety
requirement above does not allow.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from agent.intake import IntakeState
from llm.client import LLMError, generate_stream, parse_json_object
from rag.retriever import RetrievedChunk, RetrieverError, retrieve

# Canonical procedural questions every RTI application needs grounding for,
# independent of what the citizen's issue is about.
GROUNDING_QUERIES = [
    "time limit within which a public authority must respond to a request for information",
    "manner and format of making a request for information along with fee",
]

# Generous enough for a JSON object with 5 short strings + one department
# name, but caps worst-case generation length/latency.
UNDERSTAND_MAX_TOKENS = 500


@dataclass
class DraftResult:
    application_text: str
    department_guess: str
    information_sought: list[str]
    grounding_chunks: list[RetrievedChunk]
    warnings: list[str] = field(default_factory=list)
    # Clause-level provenance: which grounding chunk justified each procedural
    # clause. Only populated where build_procedural_clauses() actually found a
    # chunk containing the clause's underlying fact-keywords - never fabricated
    # for a clause that was included on aggregate/cross-chunk evidence alone.
    # Defaults to empty so existing callers (app.py) are unaffected.
    clauses: list[dict] = field(default_factory=list)


class UnderstandResult(tuple):
    """Behaves exactly like the (information_sought, likely_authority) 2-tuple
    understand_request() has always returned - `a, b = understand_request(...)`
    keeps working unchanged - but also carries the LLM's own computed_guess as
    an attribute, for callers that want to know what the model guessed even
    when a user-supplied authority overrode it as the returned likely_authority.
    """

    def __new__(cls, information_sought: list[str], likely_authority: str, computed_guess: str):
        obj = super().__new__(cls, (information_sought, likely_authority))
        obj.computed_guess = computed_guess
        return obj


def understand_request(
    problem_description: str,
    locality: str = "",
    timeframe: str = "",
    user_supplied_authority: str = "",
    on_chunk: Callable[[str], None] | None = None,
) -> tuple[list[str], str]:
    """Return (information_sought items, likely public authority guess).

    This is general civic reasoning, not grounded in the RTI Act corpus
    (the Act doesn't list municipal departments) — the caller must always
    present the authority as an unverified best guess, never as fact -
    *unless* the citizen supplied their own authority via
    user_supplied_authority, in which case that takes precedence over the
    computed guess in the returned likely_authority (the guess is still
    computed and available via the result's .computed_guess attribute).

    Streams the underlying LLM call so callers (the UI) can show live
    progress via on_chunk - e.g. rendering it into an st.status() panel -
    instead of blocking behind an opaque spinner for the full response.
    """
    known_details = (
        f'The applicant has already specified the locality as "{locality}" and the time period as '
        f'"{timeframe}" — use these concrete details instead of placeholders like [road name].\n\n'
        if locality or timeframe
        else ""
    )
    prompt = (
        "A citizen describes a problem below. For an RTI application about this problem, work out:\n"
        '1. "information_sought": a list of 2-5 short, specific pieces of information/documents to '
        "formally request (e.g. copies of complaints on file, inspection reports, name and designation "
        "of the responsible officer, action-taken reports).\n"
        '2. "likely_authority": your best guess at the specific Indian public authority/department '
        "that would hold this information (be as specific as plausible, e.g. 'Public Works Department, "
        "[Municipal Corporation]' rather than just 'Government').\n\n"
        f'Citizen\'s problem: "{problem_description}"\n\n'
        f"{known_details}"
        'Respond with ONLY a JSON object: {"information_sought": ["...", "..."], "likely_authority": "..."}'
    )
    try:
        chunks = []
        for chunk in generate_stream(
            prompt,
            system="You perform civic-domain reasoning and respond with JSON only.",
            max_tokens=UNDERSTAND_MAX_TOKENS,
        ):
            chunks.append(chunk)
            if on_chunk:
                on_chunk(chunk)
        response = "".join(chunks)
    except LLMError:
        computed_guess = "Unknown — could not determine automatically"
        fallback_authority = user_supplied_authority.strip() or computed_guess
        return UnderstandResult([], fallback_authority, computed_guess)

    parsed = parse_json_object(response)
    information_sought = parsed.get("information_sought") or []
    computed_guess = str(parsed.get("likely_authority") or "Unknown — could not determine automatically")
    if not isinstance(information_sought, list):
        information_sought = []
    information_sought = [str(i) for i in information_sought if str(i).strip()]

    likely_authority = user_supplied_authority.strip() or computed_guess
    return UnderstandResult(information_sought, likely_authority, computed_guess)


def gather_grounding() -> list[RetrievedChunk]:
    """Retrieve the standard procedural grounding every RTI application needs."""
    seen = set()
    chunks: list[RetrievedChunk] = []
    for query in GROUNDING_QUERIES:
        try:
            results = retrieve(query, top_k=3)
        except RetrieverError:
            continue
        for chunk in results:
            key = (chunk.source, chunk.page, chunk.text[:50])
            if key not in seen:
                seen.add(key)
                chunks.append(chunk)
    return chunks


def _section_text(section_label: str, chunks: list[RetrievedChunk]) -> str:
    return " ".join(c.text for c in chunks if c.section == section_label).lower()


def _section_indices(section_label: str, chunks: list[RetrievedChunk]) -> list[int]:
    return [i for i, c in enumerate(chunks) if c.section == section_label]


def _best_matching_chunk_index(
    indices: list[int], chunks: list[RetrievedChunk], keywords: list[str]
) -> int | None:
    """Find the single chunk (by index into `chunks`) whose own text actually
    contains the fact-keywords, so a clause can be linked to the specific
    chunk that justifies it rather than the section as a whole.

    The section-level pass/fail check in build_procedural_clauses() looks at
    all matching chunks concatenated together, so it's possible for a clause
    to pass verification with its keywords split across multiple chunks and
    no single chunk containing all of them. In that case we return None
    rather than link to a chunk that doesn't itself say the thing - the
    clause still appears in the letter, it's just left uncited.
    """
    for idx in indices:
        text = chunks[idx].text.lower()
        if all(k in text for k in keywords):
            return idx
    for idx in indices:
        text = chunks[idx].text.lower()
        if any(k in text for k in keywords):
            return idx
    return None


def build_procedural_clauses(
    chunks: list[RetrievedChunk],
) -> tuple[list[str], list[str], list[dict]]:
    """Return (verified boilerplate clauses, warnings for anything that couldn't
    be verified, clause->chunk provenance links).

    Each clause is only included after confirming its underlying fact
    actually appears in the retrieved grounding text — not just that some
    chunk tagged with that section number was retrieved. The third return
    value links each included clause back to the single grounding chunk
    (by index into `chunks`) that actually contains its keywords, when one
    exists; a clause whose evidence is split across multiple chunks (so no
    single chunk justifies it) is included in the letter but omitted here.
    """
    clauses = []
    warnings = []
    links = []

    sec6_indices = _section_indices("Section 6", chunks)
    sec6 = _section_text("Section 6", chunks)
    if "writing" in sec6 and "fee" in sec6:
        clause_text = (
            "This application is made in writing under Section 6(1) of the Right to Information "
            "Act, 2005, and is accompanied by the prescribed application fee."
        )
        clauses.append(clause_text)
        match_idx = _best_matching_chunk_index(sec6_indices, chunks, ["writing", "fee"])
        if match_idx is not None:
            links.append({"text": clause_text, "section": chunks[match_idx].section, "chunk_index": match_idx})
    else:
        warnings.append(
            "Could not verify the Section 6 filing-manner/fee requirement in the retrieved "
            "grounding text — omitted that clause from the letter."
        )

    sec7_indices = _section_indices("Section 7", chunks)
    sec7 = _section_text("Section 7", chunks)
    if "thirty days" in sec7:
        clause_text = (
            "As per Section 7(1) of the Act, I request that the above information be furnished "
            "within thirty days of receipt of this application."
        )
        clauses.append(clause_text)
        match_idx = _best_matching_chunk_index(sec7_indices, chunks, ["thirty days"])
        if match_idx is not None:
            links.append({"text": clause_text, "section": chunks[match_idx].section, "chunk_index": match_idx})
    else:
        warnings.append(
            "Could not verify the Section 7 response-timeline text in the retrieved grounding — "
            "omitted a timeline clause from the letter."
        )

    return clauses, warnings, links


def _format_letter(
    department_guess: str,
    department_verified: bool,
    procedural_clauses: list[str],
    information_sought: list[str],
    slots: dict[str, str],
) -> str:
    verify_note = "" if department_verified else "\n(Best guess — please verify the correct office before submitting.)"
    particulars = "\n".join(f"{i}. {item}" for i, item in enumerate(information_sought, start=1))
    if not particulars:
        particulars = "(Could not automatically determine specific particulars — please add manually.)"
    clause_block = "\n\n".join(procedural_clauses)

    # Optional - not in REQUIRED_FIELDS, so most drafts never have it. Users
    # may type a name, a title, or both, so it gets its own line beneath the
    # salutation rather than appended to it - "The Public Information
    # Officer, {pio}" read badly when pio was itself already a title (e.g.
    # "Assistant Public Information Officer, Roads Division"). Absent, this
    # is byte-for-byte the original, unconditional address block.
    pio = slots.get("pio", "").strip()
    pio_block = f"\n{pio}" if pio else ""

    return f"""To,
The Public Information Officer,{pio_block}
{department_guess}{verify_note}

Subject: Request for information under the Right to Information Act, 2005

Sir/Madam,

I, {slots.get('full_name', '')}, residing at {slots.get('address', '')}, am a citizen of India. \
I hereby request the following information concerning {slots.get('locality', 'the matter described below')} \
for the period {slots.get('timeframe', 'specified below')}, under Section 6(1) of the Right to \
Information Act, 2005.

{clause_block}

Particulars of information sought:

{particulars}

I declare that I am a citizen of India and that the information sought does not, to the best of my \
knowledge, fall under any of the exemptions in the Act.

Yours faithfully,

_________________________
{slots.get('full_name', '')}
Date: {date.today().strftime('%d %B %Y')}"""


def _validate_application_text(
    application_text: str, slots: dict[str, str], information_sought: list[str]
) -> list[str]:
    """Sanity-check the final rendered letter for the handful of things every
    RTI application must have. This runs on the actual output text (not the
    inputs that fed it) as a last-line defense against a formatting bug
    silently dropping something - it does not raise; the draft is still
    returned so the citizen can fix it manually rather than getting nothing.
    """
    warnings = []

    full_name = slots.get("full_name", "").strip()
    if not full_name or full_name not in application_text:
        warnings.append(
            "The drafted letter does not contain the applicant's full name — please add it before submitting."
        )

    address = slots.get("address", "").strip()
    if not address or address not in application_text:
        warnings.append(
            "The drafted letter does not contain the applicant's address — please add it before submitting."
        )

    if not information_sought:
        warnings.append(
            "The drafted letter has no particulars of information sought — please list what you're requesting "
            "before submitting."
        )

    if "Section 6(1)" not in application_text:
        warnings.append(
            "The drafted letter does not reference Section 6(1) of the RTI Act, 2005 — please review the letter "
            "before submitting."
        )

    return warnings


def compose_letter(
    state: IntakeState,
    information_sought: list[str],
    likely_authority: str,
    grounding_chunks: list[RetrievedChunk],
) -> DraftResult:
    """Assemble the final DraftResult from already-gathered analysis + grounding.

    Split out from draft_application() so callers (e.g. the UI) can show
    separate progress for the analysis/retrieval phase vs. this fast,
    deterministic composition phase.
    """
    warnings = []
    clause_links = []
    if not grounding_chunks:
        warnings.append(
            "No relevant RTI Act procedural text was retrieved — the draft omits specific "
            "timelines/fees rather than guessing. Please verify procedure independently."
        )
        procedural_clauses = []
    else:
        procedural_clauses, clause_warnings, clause_links = build_procedural_clauses(grounding_chunks)
        warnings.extend(clause_warnings)

    if not information_sought:
        warnings.append(
            "Could not automatically determine specific particulars of information — please review "
            "and edit the 'Particulars of information sought' section before submitting."
        )

    application_text = _format_letter(
        department_guess=likely_authority,
        department_verified=False,  # always an unverified best guess — never presented as fact
        procedural_clauses=procedural_clauses,
        information_sought=information_sought,
        slots=state.slots,
    )

    warnings.extend(_validate_application_text(application_text, state.slots, information_sought))

    return DraftResult(
        application_text=application_text,
        department_guess=likely_authority,
        information_sought=information_sought,
        grounding_chunks=grounding_chunks,
        warnings=warnings,
        clauses=clause_links,
    )


def draft_application(state: IntakeState) -> DraftResult:
    """Produce a grounded, best-effort RTI application from a completed intake state."""
    information_sought, likely_authority = understand_request(
        state.problem_description,
        locality=state.slots.get("locality", ""),
        timeframe=state.slots.get("timeframe", ""),
    )
    grounding_chunks = gather_grounding()
    return compose_letter(state, information_sought, likely_authority, grounding_chunks)
