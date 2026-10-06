"""The details an RTI application needs beyond the citizen's free-text
problem description. web/api/draft.py fills IntakeState.slots from the form;
REQUIRED_FIELDS names the slot keys (the strings were the old chat UI's
questions, kept as a description of each field).
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
