"""Pydantic request/response models for the web/ API layer."""
from pydantic import BaseModel


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


class ChunkOut(BaseModel):
    text: str
    section: str
    page: int
    source: str
    distance: float


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
