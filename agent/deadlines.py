"""Statutory deadline grounding for /track (Gate 13).

Every deadline shown to the citizen is retrieved from the Act's own corpus,
never hardcoded from memory - see gather_deadline_rules(). A rule is only
included if a retrieved chunk actually contains the specific keywords that
back its claim (the same discipline as agent/drafter.py's
build_procedural_clauses()); a rule whose grounding can't be found in the
corpus is dropped and flagged as a warning, never guessed at.

Scope decision on second appeal: only deadlines computable from a single
"date filed" input get a specific computed date - the PIO response deadline
(Section 7(1)) and the first-appeal filing deadline (Section 19(1),
grounded in "thirty days from the expiry of such period"). The second
appeal (Section 19(3)) is shown as an explanatory, cited recourse WITHOUT a
computed date: its 90-day window runs from when the first appeal's own
decision was due (Section 19(6)), which depends on when the first appeal
was actually filed - a date this tracker doesn't collect. Chaining a
worst-case date off the original filing date alone would be exactly the
kind of unsupported precision the "no fabricated content" rule exists to
prevent - an invented date is still invented even if every individual
component of the chain is separately grounded.
"""
from dataclasses import dataclass

from rag.retriever import RetrievedChunk, RetrieverError, retrieve

# top_k values below were tuned against this project's actual corpus (see
# Gate 13 grounding investigation) - "free of charge...fails to comply"
# needed a higher top_k than the others to reliably surface Section 7(6),
# whose embedding doesn't score as close to natural-language phrasings of
# its own content as the other provisions do. Verified directly: with
# top_k=10 the target chunk appears at rank 3, well inside MAX_RELEVANT_DISTANCE.
RULE_DEFINITIONS = [
    {
        "id": "response_standard",
        "label": "PIO response deadline",
        "section": "Section 7(1)",
        "query": "time limit within which a public authority must respond to a request for information",
        "top_k": 5,
        "required_keywords": ["thirty days"],
        "offset_days": 30,
        "offset_hours": None,
        "anchor": "filed",
        "applies_when": "standard",
    },
    {
        "id": "response_life_liberty",
        "label": "PIO response deadline (life or liberty)",
        "section": "Section 7(1) proviso",
        # Same query as response_standard - both provisions live in the same
        # chunk of the Act's text (the proviso immediately follows the
        # thirty-day rule in Section 7(1)) - so this reliably lands on the
        # identical chunk, just verified against different keywords.
        "query": "time limit within which a public authority must respond to a request for information",
        "top_k": 5,
        "required_keywords": ["forty-eight hours", "life or liberty"],
        "offset_days": None,
        "offset_hours": 48,
        "anchor": "filed",
        "applies_when": "life_liberty",
    },
    {
        "id": "fee_waiver",
        "label": "Fee waiver if the deadline is missed",
        "section": "Section 7(6)",
        "query": "free of charge failure to comply with time limit sub-section 1",
        "top_k": 10,
        "required_keywords": ["free of charge", "fails to comply"],
        "offset_days": None,
        "offset_hours": None,
        "anchor": None,  # informational only - not itself a deadline
        "applies_when": "always",
    },
    {
        "id": "first_appeal",
        "label": "Deadline to file a first appeal",
        "section": "Section 19(1)",
        "query": "first appeal time limit thirty days from the date of decision",
        "top_k": 5,
        "required_keywords": ["thirty days", "appeal"],
        "offset_days": 30,
        "offset_hours": None,
        "anchor": "response_deadline",  # chained: response deadline + 30 days
        "applies_when": "always",
    },
    {
        "id": "second_appeal",
        "label": "Second appeal to the Information Commission",
        "section": "Section 19(3)",
        "query": "second appeal to the Information Commission time limit ninety days",
        "top_k": 5,
        "required_keywords": ["ninety days", "second appeal"],
        "offset_days": None,
        "offset_hours": None,
        "anchor": None,  # informational only - see module docstring
        "applies_when": "always",
    },
]


@dataclass
class DeadlineRule:
    id: str
    label: str
    section: str
    chunk_index: int
    offset_days: int | None
    offset_hours: int | None
    anchor: str | None
    applies_when: str


def gather_deadline_rules() -> tuple[list[DeadlineRule], list[RetrievedChunk], list[str]]:
    """Retrieve and verify grounding for every rule in RULE_DEFINITIONS.

    Returns (grounded rules, the distinct chunks they cite - deduplicated
    and shared by chunk_index exactly like agent/drafter.py's clause links,
    warnings for any rule whose grounding couldn't be verified in the
    corpus). A rule is included only if at least one retrieved chunk
    contains every one of its required_keywords (case-insensitive substring
    match) - the same "verify before citing" discipline used throughout
    this project, not a new pattern invented for this gate.
    """
    chunks: list[RetrievedChunk] = []
    chunk_index_by_key: dict[tuple, int] = {}
    rules: list[DeadlineRule] = []
    warnings: list[str] = []

    for rule_def in RULE_DEFINITIONS:
        try:
            retrieved = retrieve(rule_def["query"], top_k=rule_def["top_k"])
        except RetrieverError:
            retrieved = []

        match_idx = None
        for c in retrieved:
            text_lower = c.text.lower()
            if all(kw in text_lower for kw in rule_def["required_keywords"]):
                key = (c.source, c.page, c.text[:50])
                if key not in chunk_index_by_key:
                    chunk_index_by_key[key] = len(chunks)
                    chunks.append(c)
                match_idx = chunk_index_by_key[key]
                break

        if match_idx is None:
            warnings.append(
                f"Could not verify {rule_def['section']} ({rule_def['label']}) in the retrieved "
                "grounding text - this deadline is omitted rather than shown unverified."
            )
            continue

        rules.append(
            DeadlineRule(
                id=rule_def["id"],
                label=rule_def["label"],
                section=rule_def["section"],
                chunk_index=match_idx,
                offset_days=rule_def["offset_days"],
                offset_hours=rule_def["offset_hours"],
                anchor=rule_def["anchor"],
                applies_when=rule_def["applies_when"],
            )
        )

    return rules, chunks, warnings
