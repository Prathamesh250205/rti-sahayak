"""Conversational slot-filling: collect the details an RTI application needs
beyond the citizen's free-text problem description, asking one question at a
time and tracking what's already been provided.
"""
from dataclasses import dataclass, field

REQUIRED_FIELDS: dict[str, str] = {
    "full_name": "What is your full name, as it should appear on the application?",
    "address": "What is your postal address? (This is where the authority will send its response.)",
    "locality": "Which locality, ward, or area does this concern? (Helps identify the right office.)",
    "timeframe": "What time period does this concern? (e.g. 'since March 2026' or 'the last 4 months')",
}


@dataclass
class IntakeState:
    problem_description: str
    slots: dict[str, str] = field(default_factory=dict)


def missing_fields(state: IntakeState) -> list[str]:
    return [f for f in REQUIRED_FIELDS if not state.slots.get(f, "").strip()]


def is_complete(state: IntakeState) -> bool:
    return not missing_fields(state)


def next_question(state: IntakeState) -> str | None:
    """Return the next question to ask, or None if all fields are filled."""
    missing = missing_fields(state)
    return REQUIRED_FIELDS[missing[0]] if missing else None


def process_reply(state: IntakeState, user_message: str) -> IntakeState:
    """Assign the user's reply verbatim to whichever field was just asked about.

    Deliberately no LLM call and no cross-field inference: the reply is
    assigned only to the field next_question() just asked for, exactly as
    typed. Earlier this used an LLM to guess which field(s) a reply matched
    semantically across the whole missing set, which could misroute a reply
    to the wrong field (e.g. a reply meant for "address" landing in
    "timeframe" because the model thought it fit better) and could rephrase
    or compute values the user never stated outright — unacceptable for a
    legal filing. Direct assignment can't do either.
    """
    missing = missing_fields(state)
    if not missing:
        return state

    value = user_message.strip()
    if value:
        state.slots[missing[0]] = value

    return state
