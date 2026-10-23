"""Request and response models for the HTTP API."""

from typing import Literal

from pydantic import BaseModel, Field


class LanguageOut(BaseModel):
    code: str
    name: str


class BookOut(BaseModel):
    id: int
    title: str
    author: str
    description: str
    source_language: str
    source_language_name: str
    publication_details: str
    page_count: int
    status: str
    status_label: str
    created_at: str


class PageSummary(BaseModel):
    page_number: int
    ocr_status: str
    review_status: str
    ocr_confidence: float | None


class PageDetail(BaseModel):
    page_number: int
    ocr_status: str
    review_status: str
    ocr_confidence: float | None
    ocr_text: str
    corrected_text: str | None
    text: str
    error: str | None
    has_image: bool
    ocr_engine: str | None


class TextUpdate(BaseModel):
    text: str = Field(max_length=200_000)


class SearchHitOut(BaseModel):
    page_number: int
    snippet: str


class OcrStartRequest(BaseModel):
    engine: Literal["tesseract", "careful"] = "tesseract"
    first_page: int | None = Field(default=None, ge=1)
    last_page: int | None = Field(default=None, ge=1)
    retry_failed: bool = False


class ApproveRangeRequest(BaseModel):
    first_page: int = Field(ge=1)
    last_page: int = Field(ge=1)


class RereadRequest(BaseModel):
    engine: Literal["tesseract", "careful"] = "tesseract"
    first_page: int = Field(ge=1)
    last_page: int = Field(ge=1)
    discard_corrections: bool = False


class OcrJobOut(BaseModel):
    status: str
    total: int
    completed: int
    failed: int


class EngineAccuracyOut(BaseModel):
    pages: int
    error_rate: float | None


class AccuracyOut(BaseModel):
    pages: int
    error_rate: float | None
    by_engine: dict[str, EngineAccuracyOut] = {}


class EngineStatusOut(BaseModel):
    ready: bool
    message: str | None


class OcrStatusOut(BaseModel):
    running: bool
    error: str | None
    ready: bool
    ready_message: str | None
    page_counts: dict[str, int]
    review_counts: dict[str, int]
    job: OcrJobOut | None
    accuracy: AccuracyOut
    engines: dict[str, EngineStatusOut]
