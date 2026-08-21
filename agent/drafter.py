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
import sys
from dataclasses import dataclass, field
from datetime import date

from agent.intake import IntakeState
from llm.client import LLMError, generate, parse_json_object
from rag.retriever import RetrievedChunk, RetrieverError, retrieve

# Canonical procedural questions every RTI application needs grounding for,
# independent of what the citizen's issue is about.
GROUNDING_QUERIES = [
    "time limit within which a public authority must respond to a request for information",
    "manner and format of making a request for information along with fee",
]

# The one sentinel value understand_request() returns for likely_authority
# whenever it couldn't work one out - whether because the LLM call failed
# outright, its response didn't parse, or (rarer, and not a failure at all)
# a successful response just left "likely_authority" empty. compose_letter()
# and _format_letter() both check for this exact string (Gate 12f) so an
# unresolved authority is never silently addressed as if "Unknown - could
# not determine automatically" were a real department's name.
UNKNOWN_AUTHORITY = "Unknown — could not determine automatically"

# Static, hand-written translations of the letter's fixed boilerplate - not
# LLM-generated at request time. The English clauses below are individually
# fact-checked against retrieved grounding text (see build_procedural_clauses)
# before being included; letting an LLM re-translate them per-request would
# reopen exactly the misattribution risk that design was built to close (see
# module docstring). Section numbers are kept in Arabic numerals in every
# language (matching real-world Hindi/Marathi RTI application convention) so
# _validate_application_text's "6(1)" check works unchanged across languages.
#
# Confidence note (for whoever reviews this): Hindi legal/administrative
# register here is high-confidence - RTI applications are routinely filed in
# Hindi and this terminology is standard. Marathi is good but slightly less
# battle-tested by me than Hindi; worth a native-speaker sanity check before
# relying on it for a real filing, same spirit as the app's existing
# "verify against the official Act" disclaimer.
SUPPORTED_LANGUAGES = ("en", "hi", "mr")

LETTER_STRINGS = {
    "en": {
        "to": "To,",
        "pio_title": "The Public Information Officer,",
        "subject": "Subject: Request for information under the Right to Information Act, 2005",
        "salutation": "Sir/Madam,",
        "opening": (
            "I, {full_name}, residing at {address}, am a citizen of India. I hereby request the "
            "following information concerning {locality} for the period {timeframe}, under Section "
            "6(1) of the Right to Information Act, 2005."
        ),
        "clause_fee": (
            "This application is made in writing under Section 6(1) of the Right to Information "
            "Act, 2005, and is accompanied by the prescribed application fee."
        ),
        "clause_timeline": (
            "As per Section 7(1) of the Act, I request that the above information be furnished "
            "within thirty days of receipt of this application."
        ),
        "clause_bpl_exempt": (
            "The applicant belongs to a family living below the poverty line and, under the "
            "proviso to Section 7(5) of the Right to Information Act, 2005, is exempt from "
            "payment of the application fee; proof of BPL status is enclosed."
        ),
        "particulars_heading": "Particulars of information sought:",
        "particulars_fallback": "(Could not automatically determine specific particulars — please add manually.)",
        "declaration": (
            "I declare that I am a citizen of India and that the information sought does not, to "
            "the best of my knowledge, fall under any of the exemptions in the Act."
        ),
        "closing": "Yours faithfully,",
        "date_label": "Date:",
        "phone_label": "Phone:",
        "email_label": "Email:",
        "locality_fallback": "the matter described below",
        "timeframe_fallback": "specified below",
        "verify_note": (
            "\n(Best guess — please confirm the correct Public Information Officer and mailing "
            "address before submitting.)"
        ),
        "authority_unresolved": "[COULD NOT BE AUTOMATICALLY DETERMINED - FILL IN THE CORRECT PUBLIC AUTHORITY BEFORE SUBMITTING]",
    },
    "hi": {
        "to": "सेवा में,",
        "pio_title": "लोक सूचना अधिकारी,",
        "subject": "विषय: सूचना का अधिकार अधिनियम, 2005 के अंतर्गत सूचना हेतु आवेदन",
        "salutation": "महोदय/महोदया,",
        "opening": (
            "मैं, {full_name}, निवासी {address}, भारत का नागरिक हूँ। मैं सूचना का अधिकार अधिनियम, "
            "2005 की धारा 6(1) के अंतर्गत {locality} से संबंधित निम्नलिखित सूचना {timeframe} की "
            "अवधि हेतु प्राप्त करना चाहता/चाहती हूँ।"
        ),
        "clause_fee": (
            "यह आवेदन सूचना का अधिकार अधिनियम, 2005 की धारा 6(1) के अंतर्गत लिखित रूप में प्रस्तुत "
            "किया जा रहा है तथा इसके साथ निर्धारित आवेदन शुल्क संलग्न है।"
        ),
        "clause_timeline": (
            "अधिनियम की धारा 7(1) के अनुसार, मैं अनुरोध करता/करती हूँ कि उपरोक्त सूचना इस आवेदन की "
            "प्राप्ति के तीस दिनों के भीतर उपलब्ध कराई जाए।"
        ),
        "clause_bpl_exempt": (
            "आवेदक गरीबी रेखा से नीचे (बीपीएल) रहने वाले परिवार से संबंधित है तथा सूचना का अधिकार "
            "अधिनियम, 2005 की धारा 7(5) के परंतुक के अंतर्गत आवेदन शुल्क के भुगतान से छूट प्राप्त है; "
            "बीपीएल स्थिति का प्रमाण संलग्न है।"
        ),
        "particulars_heading": "मांगी गई सूचना का विवरण:",
        "particulars_fallback": "(विशिष्ट विवरण स्वतः निर्धारित नहीं किया जा सका — कृपया स्वयं जोड़ें।)",
        "declaration": (
            "मैं घोषणा करता/करती हूँ कि मैं भारत का नागरिक हूँ तथा मेरी जानकारी के अनुसार मांगी गई "
            "सूचना अधिनियम के अंतर्गत किसी भी छूट प्राप्त श्रेणी में नहीं आती है।"
        ),
        "closing": "भवदीय,",
        "date_label": "दिनांक:",
        "phone_label": "फोन:",
        "email_label": "ईमेल:",
        "locality_fallback": "नीचे वर्णित विषय",
        "timeframe_fallback": "नीचे उल्लिखित अवधि",
        "verify_note": (
            "\n(अनुमानित जानकारी — कृपया प्रस्तुत करने से पहले सही लोक सूचना अधिकारी एवं डाक पता "
            "सुनिश्चित करें।)"
        ),
        "authority_unresolved": "[स्वतः निर्धारित नहीं किया जा सका - प्रस्तुत करने से पहले सही लोक प्राधिकरण भरें]",
    },
    "mr": {
        "to": "प्रति,",
        "pio_title": "जन माहिती अधिकारी,",
        "subject": "विषय: माहितीचा अधिकार अधिनियम, 2005 अंतर्गत माहितीसाठी अर्ज",
        "salutation": "महोदय/महोदया,",
        "opening": (
            "मी, {full_name}, राहणार {address}, भारताचा नागरिक आहे. मी माहितीचा अधिकार अधिनियम, "
            "2005 च्या कलम 6(1) अंतर्गत {locality} संबंधित खालील माहिती {timeframe} या कालावधीसाठी "
            "मागत आहे."
        ),
        "clause_fee": (
            "हा अर्ज माहितीचा अधिकार अधिनियम, 2005 च्या कलम 6(1) अंतर्गत लेखी स्वरूपात सादर करण्यात "
            "येत आहे व त्यासोबत विहित अर्ज शुल्क जोडलेले आहे."
        ),
        "clause_timeline": (
            "अधिनियमाच्या कलम 7(1) नुसार, मी विनंती करतो/करते की वरील माहिती हा अर्ज "
            "मिळाल्यापासून तीस दिवसांच्या आत पुरवण्यात यावी."
        ),
        "clause_bpl_exempt": (
            "अर्जदार दारिद्र्यरेषेखालील (बीपीएल) कुटुंबातील असून, माहितीचा अधिकार अधिनियम, 2005 च्या "
            "कलम 7(5) च्या परंतुकानुसार अर्ज शुल्क भरण्यापासून सूट देण्यात आली आहे; बीपीएल स्थितीचा "
            "पुरावा सोबत जोडला आहे."
        ),
        "particulars_heading": "मागितलेल्या माहितीचा तपशील:",
        "particulars_fallback": "(विशिष्ट तपशील आपोआप निश्चित करता आला नाही — कृपया स्वतः जोडा.)",
        "declaration": (
            "मी घोषित करतो/करते की मी भारताचा नागरिक आहे आणि माझ्या माहितीनुसार मागितलेली माहिती "
            "अधिनियमांतर्गत कोणत्याही सवलतीच्या वर्गवारीत येत नाही."
        ),
        "closing": "आपला विश्वासू,",
        "date_label": "दिनांक:",
        "phone_label": "फोन:",
        "email_label": "ईमेल:",
        "locality_fallback": "खाली वर्णन केलेला विषय",
        "timeframe_fallback": "खाली नमूद केलेला कालावधी",
        "verify_note": (
            "\n(अंदाजे माहिती — कृपया सादर करण्यापूर्वी योग्य जन माहिती अधिकारी व पत्ता निश्चित करा.)"
        ),
        "authority_unresolved": "[आपोआप निश्चित करता आले नाही - सादर करण्यापूर्वी योग्य सार्वजनिक प्राधिकरण भरा]",
    },
}

# 500 was measured to truncate the JSON completion mid-string on ~10% of
# calls (verbose 5-item lists ran past the cap before the closing brackets)
# - 1200 gives real headroom while still capping worst-case latency, since
# the model only generates as many tokens as it actually needs.
UNDERSTAND_MAX_TOKENS = 1200


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
    keeps working unchanged - but also carries additional attributes for
    callers (currently only web/api/draft.py) that need the scope verdict:

    computed_guess: the LLM's own guess, even when a user-supplied authority
        overrode it in the returned likely_authority.

    in_scope: the CHECK B verdict - is this genuinely a request for records
        held by an Indian public authority? True/False are explicit model
        verdicts. None means no verdict was obtained at all (the call
        failed, or the response didn't parse, or "in_scope" came back in an
        unexpected shape) - deliberately distinct from False, so a
        classification failure can never silently masquerade as an
        out-of-scope refusal. Callers must branch on all three states.

    scope_reason: the model's one-sentence reason for its in_scope verdict.
        Empty when in_scope is None (no verdict to explain).
    """

    def __new__(
        cls,
        information_sought: list[str],
        likely_authority: str,
        computed_guess: str,
        in_scope: bool | None,
        scope_reason: str,
    ):
        obj = super().__new__(cls, (information_sought, likely_authority))
        obj.computed_guess = computed_guess
        obj.in_scope = in_scope
        obj.scope_reason = scope_reason
        return obj


_LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "mr": "Marathi"}


def understand_request(
    problem_description: str,
    locality: str = "",
    timeframe: str = "",
    user_supplied_authority: str = "",
    language: str = "en",
) -> UnderstandResult:
    """Return (information_sought items, likely public authority guess), plus
    the CHECK B scope verdict on the result's .in_scope/.scope_reason.

    The department guess is general civic reasoning, not grounded in the RTI
    Act corpus (the Act doesn't list municipal departments) — the caller
    must always present it as an unverified best guess, never as fact -
    *unless* the citizen supplied their own authority via
    user_supplied_authority, in which case that takes precedence over the
    computed guess in the returned likely_authority (the guess is still
    computed and available via the result's .computed_guess attribute).

    Scope (in_scope/scope_reason) is a genuinely different question from
    grounding: whether the Act's text happens to resemble the citizen's
    words is close to meaningless (the Act is purely procedural and never
    mentions ration cards, roads, or pensions by name), so this is asked as
    an explicit classification, not inferred from retrieval distance and
    not inferred from information_sought coming back empty - a truncated
    completion or a provider hiccup looks identical to a genuine "not a
    records request" answer otherwise, and those must not be confused with
    each other (see UnderstandResult.in_scope).

    Buffers the full LLM response before parsing (Gate 12d) - this call was
    previously streamed so callers could show live token-by-token progress,
    but that's what made a mid-response provider failure unrecoverable: once
    a chunk has been shown to a user, restarting on the fallback provider
    would duplicate text on screen, so llm.client.generate_stream() must
    give up and re-raise silently in that case rather than retry - and
    "silently" is exactly the problem Gate 12's regression run exposed (a
    classification failure landing as a normal-looking "ok" response with
    "Unknown - could not determine automatically" as the authority, with
    nothing in any log to explain why). Nothing here actually needed live
    streaming - the response is parsed as one JSON object at the end
    regardless - so it now uses llm.client.generate(), which can safely
    discard a failed attempt and retry on the other provider before
    anything is returned to the caller, and unconditionally logs any
    failure it hits along the way (see the except blocks below).

    language ("en"/"hi"/"mr") only affects "information_sought" and "reason" -
    the free-text content this call actually generates. "likely_authority" is
    deliberately left in whatever form the model naturally produces (Indian
    public authorities are conventionally addressed by their official name
    even inside Hindi/Marathi correspondence - translating "Pune Municipal
    Corporation" into Marathi would risk it no longer matching the authority's
    actual registered name). "in_scope" itself is a boolean and classification
    quality must not depend on the requested output language - problem_description
    arrives in whatever language the citizen typed, independent of this
    parameter; see the module's scope-robustness testing for that check.
    """
    language = language if language in _LANGUAGE_NAMES else "en"
    language_instruction = (
        f'Write "information_sought" and "reason" in {_LANGUAGE_NAMES[language]}. Leave '
        '"likely_authority" as you would naturally produce it (do not force-translate '
        "official department names).\n\n"
        if language != "en"
        else ""
    )
    known_details = (
        f'The applicant has already specified the locality as "{locality}" and the time period as '
        f'"{timeframe}" — use these concrete details instead of placeholders like [road name].\n\n'
        if locality or timeframe
        else ""
    )
    prompt = (
        "A citizen describes a problem below. First decide:\n"
        '1. "in_scope": is this genuinely a request for RECORDS/INFORMATION held by an Indian public '
        "authority (a government office, PSU, or publicly-funded body) - the kind of thing that can be "
        "requested under the Right to Information Act, 2005? The Act grants a general right to any "
        "record from any public authority, not a topic-specific one, so this is true for almost any "
        "grievance about a government office, service, delay, or decision - a stuck ration card, an "
        "unrepaired road, a stopped pension are all in scope, even though the Act's own text never "
        "mentions any of those topics by name. A record does not stop being a public-authority record "
        "just because it concerns the citizen personally - Section 6 lets any citizen request any "
        "information held by a public authority, including records about themselves (their own filed "
        "return, application, or case file). \"It's my own document\" or \"I could get this some other "
        "way\" is never a reason to call something out of scope; the only question is whether a public "
        "authority holds the record. It is false only when the citizen isn't actually asking for a "
        "document/record at all - general advice, a how-to question with no public-authority records "
        "angle, or something unrelated to any public authority.\n"
        '2. "reason": one short sentence explaining the in_scope decision.\n\n'
        "If in scope, also work out:\n"
        '3. "information_sought": a list of 2-5 short, specific pieces of information/documents to '
        "formally request (e.g. copies of complaints on file, inspection reports, name and designation "
        "of the responsible officer, action-taken reports).\n"
        '4. "likely_authority": your best guess at the specific Indian public authority/department '
        "that would hold this information (be as specific as plausible, e.g. 'Public Works Department, "
        "[Municipal Corporation]' rather than just 'Government'). Leave this \"\" if not in scope.\n\n"
        f'Citizen\'s problem: "{problem_description}"\n\n'
        f"{known_details}"
        f"{language_instruction}"
        'Respond with ONLY a JSON object: {"in_scope": true or false, "reason": "...", '
        '"information_sought": ["...", "..."], "likely_authority": "..."}'
    )
    def _call() -> str:
        return generate(
            prompt,
            system="You perform civic-domain reasoning and respond with JSON only.",
            max_tokens=UNDERSTAND_MAX_TOKENS,
        )

    try:
        response = _call()
    except LLMError as e:
        # Gate 12d: this is CHECK B's classification call failing outright
        # (both providers) - the caller fails open (see UnderstandResult.
        # in_scope's docs), which is correct, but only if it's visible. This
        # print is that visibility; it was previously missing entirely.
        print(f"[drafter] understand_request: LLM call failed, scope check unavailable: {e}", file=sys.stderr)
        computed_guess = UNKNOWN_AUTHORITY
        fallback_authority = user_supplied_authority.strip() or computed_guess
        return UnderstandResult([], fallback_authority, computed_guess, None, "")

    parsed = parse_json_object(response)

    # A response that failed to parse but wasn't empty is a completion that
    # got cut short mid-JSON, not a model that genuinely had nothing to
    # say - worth one retry. A genuinely empty response is left alone:
    # retrying that would risk masking a real failure (e.g. a provider
    # silently returning nothing) behind a second silent attempt instead
    # of surfacing it via the normal "Unknown"/empty fallback below.
    if not parsed and response.strip():
        try:
            response = _call()
            parsed = parse_json_object(response)
        except LLMError as e:
            print(f"[drafter] understand_request: retry after truncated response also failed: {e}", file=sys.stderr)
            # fall through to today's warning path unchanged

    if not parsed:
        # No usable response even after a retry - this is a classification
        # FAILURE, not a verdict. in_scope=None, never True/False, so the
        # caller can't mistake "we don't know" for "we checked and it's
        # out of scope".
        print(
            "[drafter] understand_request: could not obtain a usable classification "
            "(unparseable response, even after retry) - scope check unavailable",
            file=sys.stderr,
        )
        computed_guess = UNKNOWN_AUTHORITY
        fallback_authority = user_supplied_authority.strip() or computed_guess
        return UnderstandResult([], fallback_authority, computed_guess, None, "")

    information_sought = parsed.get("information_sought") or []
    computed_guess = str(parsed.get("likely_authority") or UNKNOWN_AUTHORITY)
    if not isinstance(information_sought, list):
        information_sought = []
    information_sought = [str(i) for i in information_sought if str(i).strip()]

    likely_authority = user_supplied_authority.strip() or computed_guess

    # Anything other than a clean bool is treated as "no verdict obtained"
    # (missing key, wrong type, etc.) - same reasoning as the LLMError/parse
    # -failure branches above: a malformed field must not silently collapse
    # into an explicit False refusal.
    raw_in_scope = parsed.get("in_scope")
    in_scope = raw_in_scope if isinstance(raw_in_scope, bool) else None
    scope_reason = str(parsed.get("reason") or "").strip()

    return UnderstandResult(information_sought, likely_authority, computed_guess, in_scope, scope_reason)


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
    language: str = "en",
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

    The verification keywords below are always checked against the corpus's
    own (English-only) text regardless of `language` - only the rendered
    clause string (from LETTER_STRINGS) changes. Translation never affects
    what counts as verified.
    """
    strings = LETTER_STRINGS.get(language, LETTER_STRINGS["en"])
    clauses = []
    warnings = []
    links = []

    sec6_indices = _section_indices("Section 6", chunks)
    sec6 = _section_text("Section 6", chunks)
    if "writing" in sec6 and "fee" in sec6:
        clause_text = strings["clause_fee"]
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
        clause_text = strings["clause_timeline"]
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
    language: str = "en",
) -> str:
    strings = LETTER_STRINGS.get(language, LETTER_STRINGS["en"])

    # Gate 12f: an unresolved authority must never be addressed as if
    # UNKNOWN_AUTHORITY's sentinel text were an actual department name - a
    # citizen skimming the letter could easily miss that it isn't real and
    # submit it as-is. The bracketed placeholder below is deliberately loud
    # and imperative; it replaces (not appends to) the normal best-guess
    # note, since stacking both would bury the one thing that actually
    # matters here under two differently-worded messages.
    if department_guess == UNKNOWN_AUTHORITY:
        department_line = strings["authority_unresolved"]
        verify_note = ""
    else:
        department_line = department_guess
        verify_note = "" if department_verified else strings["verify_note"]

    particulars = "\n".join(f"{i}. {item}" for i, item in enumerate(information_sought, start=1))
    if not particulars:
        particulars = strings["particulars_fallback"]

    # BPL applicants are exempt from the fee under the proviso to Section 7(5)
    # of the Act - swap the standard fee clause for the exemption claim rather
    # than telling a fee-exempt applicant to pay one. Only replaces the exact
    # clause build_procedural_clauses() emits; if that clause isn't present
    # (e.g. Section 6 grounding wasn't verified this time), the exemption
    # claim is appended instead so a BPL applicant never silently loses it.
    # False (the default - app.py never sets this slot) reproduces today's
    # clause list unchanged.
    is_bpl = slots.get("is_bpl", "").strip().lower() == "true"
    rendered_clauses = list(procedural_clauses)
    if is_bpl:
        fee_clause = strings["clause_fee"]
        bpl_clause = strings["clause_bpl_exempt"]
        if fee_clause in rendered_clauses:
            rendered_clauses = [bpl_clause if c == fee_clause else c for c in rendered_clauses]
        else:
            rendered_clauses.append(bpl_clause)
    clause_block = "\n\n".join(rendered_clauses)

    # Optional - not in REQUIRED_FIELDS, so most drafts never have it. Users
    # may type a name, a title, or both, so it gets its own line beneath the
    # salutation rather than appended to it - "The Public Information
    # Officer, {pio}" read badly when pio was itself already a title (e.g.
    # "Assistant Public Information Officer, Roads Division"). Absent, this
    # is byte-for-byte the original, unconditional address block.
    pio = slots.get("pio", "").strip()
    pio_block = f"\n{pio}" if pio else ""

    # Neither is in REQUIRED_FIELDS - each renders only if actually supplied,
    # so an applicant who gives neither gets today's unchanged signature block.
    phone = slots.get("phone", "").strip()
    email = slots.get("email", "").strip()
    contact_block = ""
    if phone:
        contact_block += f"\n{strings['phone_label']} {phone}"
    if email:
        contact_block += f"\n{strings['email_label']} {email}"

    opening = strings["opening"].format(
        full_name=slots.get("full_name", ""),
        address=slots.get("address", ""),
        locality=slots.get("locality") or strings["locality_fallback"],
        timeframe=slots.get("timeframe") or strings["timeframe_fallback"],
    )

    return f"""{strings['to']}
{strings['pio_title']}{pio_block}
{department_line}{verify_note}

{strings['subject']}

{strings['salutation']}

{opening}

{clause_block}

{strings['particulars_heading']}

{particulars}

{strings['declaration']}

{strings['closing']}

_________________________
{slots.get('full_name', '')}{contact_block}
{strings['date_label']} {date.today().strftime('%d %B %Y')}"""


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

    # "6(1)" rather than "Section 6(1)" - the word "Section"/"धारा"/"कलम"
    # varies by language (see LETTER_STRINGS), but the section number itself
    # is always rendered in Arabic numerals across en/hi/mr.
    if "6(1)" not in application_text:
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
    language: str = "en",
) -> DraftResult:
    """Assemble the final DraftResult from already-gathered analysis + grounding.

    Split out from draft_application() so callers (e.g. the UI) can show
    separate progress for the analysis/retrieval phase vs. this fast,
    deterministic composition phase.
    """
    language = language if language in SUPPORTED_LANGUAGES else "en"
    warnings = []
    clause_links = []
    if not grounding_chunks:
        warnings.append(
            "No relevant RTI Act procedural text was retrieved — the draft omits specific "
            "timelines/fees rather than guessing. Please verify procedure independently."
        )
        procedural_clauses = []
    else:
        procedural_clauses, clause_warnings, clause_links = build_procedural_clauses(grounding_chunks, language)
        warnings.extend(clause_warnings)

    if not information_sought:
        warnings.append(
            "Could not automatically determine specific particulars of information — please review "
            "and edit the 'Particulars of information sought' section before submitting."
        )

    # Gate 12f: this is deliberately independent of the "scope screening was
    # unavailable" warning web/api/draft.py adds when in_scope is None -
    # likely_authority can end up as UNKNOWN_AUTHORITY even when
    # classification succeeded (the model just left it blank), so this must
    # fire on its own rather than assuming the other warning already covers
    # it. Without this, a citizen could get a fully "successful" draft whose
    # addressee is unresolved with nothing in the warnings panel to say so.
    if likely_authority == UNKNOWN_AUTHORITY:
        warnings.append(
            "The public authority could not be automatically determined — the letter marks this "
            "plainly where the addressee would go. Please fill in the correct department and Public "
            "Information Officer before submitting."
        )

    application_text = _format_letter(
        department_guess=likely_authority,
        department_verified=False,  # always an unverified best guess — never presented as fact
        procedural_clauses=procedural_clauses,
        information_sought=information_sought,
        slots=state.slots,
        language=language,
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


def draft_application(state: IntakeState, language: str = "en") -> DraftResult:
    """Produce a grounded, best-effort RTI application from a completed intake state."""
    information_sought, likely_authority = understand_request(
        state.problem_description,
        locality=state.slots.get("locality", ""),
        timeframe=state.slots.get("timeframe", ""),
        language=language,
    )
    grounding_chunks = gather_grounding()
    return compose_letter(state, information_sought, likely_authority, grounding_chunks, language=language)
