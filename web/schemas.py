"""Pydantic request/response models for the web/ API layer."""
from pydantic import BaseModel, model_validator


class DraftRequest(BaseModel):
    full_name: str
    address: str
    phone: str
    email: str | None = None
    public_authority: str | None = None
    problem_description: str
    locality: str | None = None
    timeframe: str | None = None
    is_bpl: bool = False
    pio: str = ""
    language: str = "en"


class ChunkOut(BaseModel):
    text: str
    section: str
    page: int
    source: str
    distance: float
    translations: dict[str, str] = {}  # unofficial hi/mr text, filled in below

    @model_validator(mode="after")
    def _add_translations(self):
        if not self.translations:
            from web.api.act import chunk_translations
            self.translations = chunk_translations(self.text)
        return self


class ClauseOut(BaseModel):
    text: str
    section: str
    chunk_index: int


class DraftResponse(BaseModel):
    application_text: str
    department_guess: str
    information_sought: list[str]
    chunks: list[ChunkOut]
    clauses: list[ClauseOut]
    warnings: list[str]
    meta: dict
    status: str = "ok"


class PdfRequest(BaseModel):
    application_text: str


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    citations: list[ClauseOut]
    chunks: list[ChunkOut]
    warnings: list[str]
    meta: dict
    status: str = "ok"


class DeadlineRuleOut(BaseModel):
    id: str
    label: str
    section: str
    chunk_index: int
    offset_days: int | None = None
    offset_hours: int | None = None
    anchor: str | None = None
    applies_when: str


class TrackRulesResponse(BaseModel):
    rules: list[DeadlineRuleOut]
    chunks: list[ChunkOut]
    warnings: list[str]
    status: str = "ok"
