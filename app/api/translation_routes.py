"""HTTP routes for target languages and translation. All paths are under /api."""

import sqlite3
from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api import translation_jobs
from app.api.deps import get_conn, get_settings, require_book, require_user
from app.config import SUPPORTED_LANGUAGES, Settings
from app.services.translation import ProviderSetupError, get_provider, provider_status
from app.services.translation import review as translation_review
from app.services.translation import service as translation

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


class ProviderOut(BaseModel):
    name: str
    label: str
    ready: bool
    message: str | None
    is_test: bool
    model: str | None


class TargetsOut(BaseModel):
    selected: list[str]
    available: list[dict[str, str]]


class TargetsIn(BaseModel):
    languages: list[str]


class LanguageProgressOut(BaseModel):
    status: str
    total: int
    translated: int
    approved: int
    failed: int
    notes: int
    outdated: bool
    test_output: bool
    untranslated: int
    error: str | None


class ChapterProgressOut(BaseModel):
    id: int
    title: str
    order_index: int
    page_count: int
    approved_pages: int
    ready: bool
    missing_pages: list[int]
    languages: dict[str, LanguageProgressOut]


class JobOut(BaseModel):
    status: str
    total: int
    completed: int
    failed: int
    error: str | None


class OverviewOut(BaseModel):
    provider: ProviderOut
    running: bool
    error: str | None
    job: JobOut | None
    targets: list[str]
    chapters: list[ChapterProgressOut]


class StartIn(BaseModel):
    chapter_ids: list[int] | None = None
    languages: list[str] | None = None
    overwrite: bool = False


class ChunkOut(BaseModel):
    chunk_index: int
    source_text: str
    translated_text: str | None
    edited_text: str | None
    status: str
    notes: str | None
    error: str | None
    provider: str | None
    outdated: bool = False
    untranslated: bool = False


def _targets_out(conn: sqlite3.Connection, book: sqlite3.Row) -> TargetsOut:
    return TargetsOut(
        selected=translation.get_targets(conn, book["id"]),
        available=[
            {"code": code, "name": name}
            for code, (name, _tess) in SUPPORTED_LANGUAGES.items()
            if code != book["source_language"]
        ],
    )


@router.get("/translation/provider", response_model=ProviderOut)
def provider(settings: Settings = Depends(get_settings)) -> ProviderOut:
    """Which translation service is configured and whether it is ready."""
    return ProviderOut(**asdict(provider_status(settings)))


@router.get("/books/{book_id}/targets", response_model=TargetsOut)
def get_targets(book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)) -> TargetsOut:
    """The languages the book will be translated into, and the ones that can be chosen."""
    return _targets_out(conn, book)


@router.put("/books/{book_id}/targets", response_model=TargetsOut)
def put_targets(
    body: TargetsIn, book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> TargetsOut:
    """Choose the target languages (at least one; never the book's own language)."""
    translation.set_targets(conn, book["id"], body.languages)
    return _targets_out(conn, book)


@router.get("/books/{book_id}/translation", response_model=OverviewOut)
def overview(
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> OverviewOut:
    """Per chapter and language: is the source ready, and how far has translation got. Poll while running."""
    job = conn.execute(
        "SELECT status, total, completed, failed, error FROM processing_jobs "
        "WHERE book_id = ? AND job_type = 'translation' ORDER BY id DESC LIMIT 1",
        (book["id"],),
    ).fetchone()
    return OverviewOut(
        provider=ProviderOut(**asdict(provider_status(settings))),
        running=translation_jobs.is_running(book["id"]),
        error=translation_jobs.last_error(book["id"]),
        job=JobOut(**dict(job)) if job else None,
        targets=translation.get_targets(conn, book["id"]),
        chapters=[
            ChapterProgressOut(**{**asdict(c), "languages": {k: asdict(v) for k, v in c.languages.items()}})
            for c in translation.overview(conn, settings, book["id"])
        ],
    )


@router.post("/books/{book_id}/translation", status_code=202)
def start(
    body: StartIn,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Translate chapters in the background. Unfinished chunks are resumed; finished ones are never repeated."""
    if translation_jobs.is_running(book["id"]):
        raise translation.TranslationError("This book is already being translated. Please wait for it to finish.")
    try:
        translator = get_provider(settings)
    except ProviderSetupError as exc:
        raise translation.TranslationError(str(exc)) from exc
    prepared = translation.prepare(
        conn,
        settings,
        book["id"],
        chapter_ids=body.chapter_ids,
        languages=body.languages,
        overwrite=body.overwrite,
        replace_test_output=not translator.is_test,
    )
    if prepared.pending_chunks == 0:
        return {"status": "nothing_to_do", "chunks": 0, "skipped": prepared.skipped}
    translation_jobs.start(settings, book["id"], prepared.pairs, translator)
    return {"status": "started", "chunks": prepared.pending_chunks, "skipped": prepared.skipped}


def _check_language(language: str) -> None:
    if language not in SUPPORTED_LANGUAGES:
        raise translation.TranslationError("That language is not supported.")


def _chunk_out(
    conn: sqlite3.Connection, settings: Settings, book_id: int, chapter_id: int, language: str, index: int
) -> ChunkOut:
    row = translation_review.get_chunk(conn, book_id, chapter_id, language, index)
    outdated = index in translation_review.outdated_indexes(conn, settings, book_id, chapter_id)
    wrong = index in translation_review.untranslated_indexes(conn, book_id, chapter_id, language)
    return ChunkOut(
        chunk_index=row["chunk_index"],
        source_text=row["source_text"],
        translated_text=row["translated_text"],
        edited_text=row["edited_text"],
        status=row["status"],
        notes=row["notes"],
        error=row["error"],
        provider=row["provider"],
        outdated=outdated,
        untranslated=wrong,
    )


class TextIn(BaseModel):
    text: str = Field(max_length=200_000)


@router.get("/books/{book_id}/chapters/{chapter_id}/translation/{language}", response_model=list[ChunkOut])
def chunks(
    chapter_id: int,
    language: str,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> list[ChunkOut]:
    """The stored source and translated text of a chapter in one language."""
    _check_language(language)
    rows = translation.list_chunks(conn, book["id"], chapter_id, language)
    outdated = translation_review.outdated_indexes(conn, settings, book["id"], chapter_id) if rows else set()
    wrong = translation_review.untranslated_indexes(conn, book["id"], chapter_id, language) if rows else set()
    return [
        ChunkOut(**dict(row), outdated=row["chunk_index"] in outdated, untranslated=row["chunk_index"] in wrong)
        for row in rows
    ]


@router.put("/books/{book_id}/chapters/{chapter_id}/translation/{language}/{index}/text", response_model=ChunkOut)
def edit_chunk(
    chapter_id: int,
    language: str,
    index: int,
    body: TextIn,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> ChunkOut:
    """Save the author's wording for one part (it must be approved again)."""
    _check_language(language)
    translation_review.save_edit(conn, settings, book["id"], chapter_id, language, index, body.text)
    return _chunk_out(conn, settings, book["id"], chapter_id, language, index)


@router.post("/books/{book_id}/chapters/{chapter_id}/translation/{language}/{index}/approve", response_model=ChunkOut)
def approve_chunk(
    chapter_id: int,
    language: str,
    index: int,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> ChunkOut:
    """Approve one part's current text."""
    _check_language(language)
    translation_review.approve_chunk(conn, settings, book["id"], chapter_id, language, index)
    return _chunk_out(conn, settings, book["id"], chapter_id, language, index)


@router.post("/books/{book_id}/chapters/{chapter_id}/translation/{language}/{index}/restore", response_model=ChunkOut)
def restore_chunk(
    chapter_id: int,
    language: str,
    index: int,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> ChunkOut:
    """Go back to the machine translation for one part."""
    _check_language(language)
    translation_review.restore_machine(conn, settings, book["id"], chapter_id, language, index)
    return _chunk_out(conn, settings, book["id"], chapter_id, language, index)


@router.post("/books/{book_id}/chapters/{chapter_id}/translation/{language}/approve-all")
def approve_all_chunks(
    chapter_id: int,
    language: str,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> dict[str, int]:
    """Approve every part of the chapter that can be approved (an explicit action by the author)."""
    _check_language(language)
    approved, skipped = translation_review.approve_all(conn, settings, book["id"], chapter_id, language)
    return {"approved": approved, "skipped": skipped}
