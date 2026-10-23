"""Translate approved chapters chunk by chunk.

Flow: prepare (split the approved source into chunks and store them) -> run (translate each unfinished chunk with
bounded retries, saving after every chunk) -> overview (status per chapter and language). Finished chunks are never
translated again, so an interrupted run simply resumes. Approved or hand-edited translations are never replaced
without explicit confirmation.
"""

import dataclasses
import logging
import random
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.config import SUPPORTED_LANGUAGES, Settings
from app.services import chapters as chapter_service
from app.services import glossary as glossary_service
from app.services.books import BookError
from app.services.translation.base import (
    GlossaryEntry,
    PermanentProviderError,
    TransientProviderError,
    TranslationProvider,
    TranslationRequest,
)
from app.services.translation.chunking import split_into_chunks, text_hash
from app.services.translation.script import untranslated_reason

logger = logging.getLogger(__name__)

NOT_STARTED = "not_started"
PROCESSING = "processing"
AWAITING_APPROVAL = "awaiting_approval"
APPROVED = "approved"
FAILED = "failed"
IN_PROGRESS = "in_progress"
MAX_BACKOFF_SECONDS = 60.0
TEST_PROVIDER = "mock"  # output from this provider is placeholder text, not a translation
MAX_LISTED_PAGES = 12

ProgressCallback = Callable[[int, int], None]


class TranslationError(BookError):
    """A translation problem the author can fix; the message is safe to show them."""


class NeedsConfirmation(TranslationError):
    """Starting would replace approved or edited translations; the author must confirm first."""


@dataclass
class LanguageProgress:
    """Translation state of one chapter in one language."""

    status: str = NOT_STARTED
    total: int = 0
    translated: int = 0
    approved: int = 0
    failed: int = 0
    notes: int = 0
    outdated: bool = False
    test_output: bool = False
    untranslated: int = 0
    error: str | None = None


@dataclass
class ChapterProgress:
    """A chapter with its readiness and per-language translation state."""

    id: int
    title: str
    order_index: int
    page_count: int
    approved_pages: int
    ready: bool
    missing_pages: list[int]
    languages: dict[str, LanguageProgress] = field(default_factory=dict)


@dataclass(frozen=True)
class Prepared:
    """What prepare() set up."""

    pairs: list[tuple[int, str]]
    pending_chunks: int
    skipped: list[dict[str, object]]


@dataclass(frozen=True)
class RunSummary:
    """Result of one translation run."""

    total: int
    completed: int
    failed: int
    aborted: str | None


# --- target languages -------------------------------------------------------------------------------------------


def get_targets(conn: sqlite3.Connection, book_id: int) -> list[str]:
    """The target languages chosen for the book, in the order they were chosen."""
    rows = conn.execute(
        "SELECT language_code FROM target_languages WHERE book_id = ? AND selected = 1 ORDER BY id", (book_id,)
    )
    return [row["language_code"] for row in rows]


def set_targets(conn: sqlite3.Connection, book_id: int, codes: list[str]) -> list[str]:
    """Choose the target languages. At least one is required and none may equal the book's own language."""
    book = conn.execute("SELECT source_language FROM books WHERE id = ?", (book_id,)).fetchone()
    if book is None:
        raise TranslationError("That book no longer exists.")
    unique = list(dict.fromkeys(codes))
    if not unique:
        raise TranslationError("Please choose at least one language to translate into.")
    for code in unique:
        if code not in SUPPORTED_LANGUAGES:
            raise TranslationError("One of the chosen languages is not supported.")
        if code == book["source_language"]:
            raise TranslationError("A book cannot be translated into its own language.")
    with conn:
        conn.execute(
            f"DELETE FROM target_languages WHERE book_id = ? AND language_code NOT IN ({','.join('?' * len(unique))})",
            (book_id, *unique),
        )
        for code in unique:
            conn.execute(
                "INSERT INTO target_languages (book_id, language_code, selected) VALUES (?, ?, 1) "
                "ON CONFLICT (book_id, language_code) DO UPDATE SET selected = 1",
                (book_id, code),
            )
    return get_targets(conn, book_id)


# --- source text and chunks -------------------------------------------------------------------------------------


def _missing_pages(conn: sqlite3.Connection, book_id: int, chapter: sqlite3.Row) -> list[int]:
    approved = {
        row["page_number"]
        for row in conn.execute(
            "SELECT page_number FROM book_pages WHERE book_id = ? AND page_number BETWEEN ? AND ? "
            "AND ocr_status = 'done' AND review_status = 'approved'",
            (book_id, chapter["start_page"], chapter["end_page"]),
        )
    }
    return [page for page in range(chapter["start_page"], chapter["end_page"] + 1) if page not in approved]


def chapter_chunks(conn: sqlite3.Connection, settings: Settings, book_id: int, chapter: sqlite3.Row) -> list[str]:
    """Source chunks of a chapter: index 0 is the heading, the rest is the approved text only."""
    pages = chapter_service.chapter_pages(conn, book_id, chapter["id"], approved_only=True)
    heading = chapter["heading"] or chapter["title"]
    return [heading, *split_into_chunks([page.text for page in pages], settings.translation_chunk_chars)]


def _existing(conn: sqlite3.Connection, chapter_id: int, language: str) -> dict[int, sqlite3.Row]:
    rows = conn.execute(
        "SELECT id, chunk_index, source_hash, status, edited_text, translated_text, provider FROM translations "
        "WHERE chapter_id = ? AND language_code = ?",
        (chapter_id, language),
    )
    return {row["chunk_index"]: row for row in rows}


def _is_protected(row: sqlite3.Row) -> bool:
    return row["status"] == APPROVED or bool(row["edited_text"])


def keep_unchanged_terms(conn: sqlite3.Connection, book_id: int, language: str) -> list[str]:
    """Glossary terms that stay in the original script inside the translation."""
    return [t.source_term for t in glossary_service.terms_for_translation(conn, book_id, language) if t.keep_unchanged]


def untranslated_problem(
    conn: sqlite3.Connection,
    book_id: int,
    language: str,
    text: str | None,
    keep: list[str] | None = None,
    provider: str | None = None,
) -> str | None:
    """Why a stored translation does not look like the target language (still in Tamil, ...), or None.

    Test-mode placeholders are skipped: they are not translations at all (they have their own warning).
    """
    if not text or provider == TEST_PROVIDER:
        return None
    source = conn.execute("SELECT source_language FROM books WHERE id = ?", (book_id,)).fetchone()
    if source is None:
        return None
    terms = keep_unchanged_terms(conn, book_id, language) if keep is None else keep
    return untranslated_reason(text, source["source_language"], language, terms)


def _untranslated_indexes(
    conn: sqlite3.Connection, book_id: int, language: str, existing: dict[int, sqlite3.Row]
) -> set[int]:
    """Parts whose machine translation is not in the target language and that the author has not edited."""
    keep = keep_unchanged_terms(conn, book_id, language)
    return {
        index
        for index, row in existing.items()
        if not row["edited_text"]
        and untranslated_problem(conn, book_id, language, row["translated_text"], keep, row["provider"])
    }


# --- prepare ----------------------------------------------------------------------------------------------------


def prepare(
    conn: sqlite3.Connection,
    settings: Settings,
    book_id: int,
    *,
    chapter_ids: list[int] | None = None,
    languages: list[str] | None = None,
    overwrite: bool = False,
    replace_test_output: bool = False,
) -> Prepared:
    """Create or refresh the chunks to translate. Raises NeedsConfirmation if approved work would be replaced.

    With replace_test_output (a real provider is configured) placeholder text from test mode is always
    replaced and never needs confirmation: it is not a translation.
    """
    targets = get_targets(conn, book_id)
    if not targets:
        raise TranslationError("Please choose the languages to translate into first.")
    chosen = languages if languages is not None else targets
    if not chosen or any(code not in targets for code in chosen):
        raise TranslationError("Please choose those languages under 'Translate into' first.")

    all_chapters = chapter_service.list_chapters(conn, book_id)
    if not all_chapters:
        raise TranslationError("Create the chapters first. Translation works one chapter at a time.")
    wanted = all_chapters
    if chapter_ids is not None:
        by_id = {c["id"]: c for c in all_chapters}
        if any(cid not in by_id for cid in chapter_ids):
            raise TranslationError("One of the chapters was not found. Please reload the page.")
        wanted = [by_id[cid] for cid in chapter_ids]

    ready: list[sqlite3.Row] = []
    skipped: list[dict[str, object]] = []
    for chapter in wanted:
        missing = _missing_pages(conn, book_id, chapter)
        if not missing:
            ready.append(chapter)
        elif chapter_ids is not None:
            shown = ", ".join(str(p) for p in missing[:MAX_LISTED_PAGES]) + (
                " …" if len(missing) > MAX_LISTED_PAGES else ""
            )
            raise TranslationError(
                f"The chapter \"{chapter['title']}\" has pages that are not approved yet: {shown}. "
                "Only approved text is translated."
            )
        else:
            skipped.append({"id": chapter["id"], "title": chapter["title"], "missing_pages": missing})
    if not ready:
        raise TranslationError(
            "No chapter is ready. Approve all pages of a chapter first; only approved text is translated."
        )

    plans = [(c, code, chapter_chunks(conn, settings, book_id, c)) for c in ready for code in chosen]
    protected: list[str] = []
    for chapter, code, chunks in plans:
        existing = _existing(conn, chapter["id"], code)
        wrong_language = _untranslated_indexes(conn, book_id, code, existing)
        replaced = sum(
            1
            for index, row in existing.items()
            if _is_protected(row)
            and index not in wrong_language  # not a real translation: replaced without asking
            and not (replace_test_output and row["provider"] == TEST_PROVIDER)
            and (index >= len(chunks) or row["source_hash"] != text_hash(chunks[index]))
        )
        if replaced:
            name = SUPPORTED_LANGUAGES[code][0]
            protected.append(
                f"\"{chapter['title']}\" in {name} ({replaced} approved or edited part{'s' if replaced != 1 else ''})"
            )
    if protected and not overwrite:
        raise NeedsConfirmation(
            "The approved text changed since these were translated. Translating again will replace: "
            + "; ".join(protected)
            + "."
        )

    with conn:
        for chapter, code, chunks in plans:
            wrong_language = _untranslated_indexes(conn, book_id, code, _existing(conn, chapter["id"], code))
            _apply_plan(conn, chapter["id"], code, chunks, replace_test_output, wrong_language)
    pairs = [(chapter["id"], code) for chapter, code, _ in plans]
    return Prepared(pairs=pairs, pending_chunks=_pending_count(conn, pairs), skipped=skipped)


def _apply_plan(
    conn: sqlite3.Connection,
    chapter_id: int,
    language: str,
    chunks: list[str],
    replace_test_output: bool = False,
    force_reset: set[int] | None = None,
) -> None:
    existing = _existing(conn, chapter_id, language)
    for index, text in enumerate(chunks):
        digest = text_hash(text)
        row = existing.get(index)
        is_placeholder = replace_test_output and row is not None and row["provider"] == TEST_PROVIDER
        is_wrong_language = row is not None and index in (force_reset or set())
        if row is not None and row["source_hash"] == digest and not is_placeholder and not is_wrong_language:
            continue  # unchanged: keep whatever was already translated, approved or edited
        if row is None:
            conn.execute(
                "INSERT INTO translations (chapter_id, language_code, chunk_index, source_text, source_hash, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chapter_id, language, index, text, digest, NOT_STARTED),
            )
        else:
            conn.execute(
                "UPDATE translations SET source_text = ?, source_hash = ?, translated_text = NULL, edited_text = NULL, "
                "status = ?, attempts = 0, error = NULL, notes = NULL, provider = NULL, approved_at = NULL, "
                "updated_at = datetime('now') WHERE id = ?",
                (text, digest, NOT_STARTED, row["id"]),
            )
    for index, row in existing.items():
        if index >= len(chunks):
            conn.execute("DELETE FROM translations WHERE id = ?", (row["id"],))


def _pending_count(conn: sqlite3.Connection, pairs: list[tuple[int, str]]) -> int:
    total = 0
    for chapter_id, language in pairs:
        total += conn.execute(
            "SELECT COUNT(*) FROM translations WHERE chapter_id = ? AND language_code = ? AND status IN (?, ?, ?)",
            (chapter_id, language, NOT_STARTED, PROCESSING, FAILED),
        ).fetchone()[0]
    return int(total)


# --- run --------------------------------------------------------------------------------------------------------


@dataclass
class _Outcome:
    text: str | None
    error: str | None
    attempts: int
    fatal: bool = False


def _translate_with_retry(
    provider: TranslationProvider,
    request: TranslationRequest,
    settings: Settings,
    sleep: Callable[[float], None],
) -> _Outcome:
    attempt = 0
    while True:
        attempt += 1
        try:
            text = provider.translate(request)
        except TransientProviderError as exc:
            if attempt >= settings.translation_max_attempts:
                return _Outcome(None, f"{exc} Gave up after {attempt} tries.", attempt)
            delay = (
                exc.retry_after
                if exc.retry_after is not None
                else settings.translation_backoff_seconds * 2 ** (attempt - 1)
            )
            logger.warning("Transient translation error (attempt %s): %s", attempt, exc)
            sleep(min(delay, MAX_BACKOFF_SECONDS) + random.uniform(0, 0.25))
        except PermanentProviderError as exc:
            return _Outcome(None, str(exc), attempt, fatal=exc.fatal)
        else:
            keep_unchanged = [entry.term for entry in request.glossary if entry.keep_unchanged]
            reason = (
                None
                if provider.is_test  # test mode only marks the source text; it is not meant to be a translation
                else untranslated_reason(text, request.source_language, request.target_language, keep_unchanged)
            )
            if reason is None:
                return _Outcome(text, None, attempt)
            if attempt >= settings.translation_max_attempts:
                return _Outcome(
                    None, f"{reason} Gave up after {attempt} tries. Click Translate again to retry.", attempt
                )
            logger.warning("Answer not in the target language (attempt %s); asking again", attempt)
            request = dataclasses.replace(request, previous_failed=True)


def _entries_for(conn: sqlite3.Connection, book_id: int, language: str, text: str) -> tuple[GlossaryEntry, ...]:
    entries = []
    for term in glossary_service.terms_for_translation(conn, book_id, language):
        if term.source_term in text:
            entries.append(GlossaryEntry(term.source_term, term.keep_unchanged, term.translations.get(language)))
    return tuple(entries)


def _glossary_notes(entries: tuple[GlossaryEntry, ...], translated: str) -> str | None:
    notes = []
    for entry in entries:
        if entry.keep_unchanged and entry.term not in translated:
            notes.append(f'The term "{entry.term}" should stay unchanged but was not found in the translation.')
        elif entry.preferred and entry.preferred not in translated:
            notes.append(f'The preferred wording "{entry.preferred}" for "{entry.term}" was not found.')
    return " ".join(notes) or None


def run(
    conn: sqlite3.Connection,
    settings: Settings,
    book_id: int,
    pairs: list[tuple[int, str]],
    provider: TranslationProvider,
    *,
    progress: ProgressCallback | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> RunSummary:
    """Translate every unfinished chunk of the given chapter/language pairs, saving after each chunk."""
    source_language = conn.execute("SELECT source_language FROM books WHERE id = ?", (book_id,)).fetchone()[0]
    pending: list[sqlite3.Row] = []
    for chapter_id, language in pairs:
        pending += conn.execute(
            "SELECT t.id, t.chapter_id, t.language_code, t.chunk_index, t.source_text FROM translations t "
            "WHERE t.chapter_id = ? AND t.language_code = ? AND t.status IN (?, ?, ?) ORDER BY t.chunk_index",
            (chapter_id, language, NOT_STARTED, PROCESSING, FAILED),
        ).fetchall()
    with conn:
        job_id = conn.execute(
            "INSERT INTO processing_jobs (book_id, job_type, status, total, started_at) "
            "VALUES (?, 'translation', 'processing', ?, datetime('now'))",
            (book_id, len(pending)),
        ).lastrowid

    completed = failed = 0
    aborted: str | None = None
    for done, row in enumerate(pending, start=1):
        with conn:
            conn.execute("UPDATE translations SET status = ? WHERE id = ?", (PROCESSING, row["id"]))
        entries = _entries_for(conn, book_id, row["language_code"], row["source_text"])
        request = TranslationRequest(
            text=row["source_text"],
            source_language=source_language,
            target_language=row["language_code"],
            glossary=entries,
            is_heading=row["chunk_index"] == 0,
        )
        outcome = _translate_with_retry(provider, request, settings, sleep)
        with conn:
            if outcome.text is not None:
                conn.execute(
                    "UPDATE translations SET translated_text = ?, status = ?, attempts = attempts + ?, error = NULL, "
                    "notes = ?, provider = ?, updated_at = datetime('now') WHERE id = ?",
                    (
                        outcome.text,
                        AWAITING_APPROVAL,
                        outcome.attempts,
                        _glossary_notes(entries, outcome.text),
                        provider.name,
                        row["id"],
                    ),
                )
                completed += 1
            else:
                conn.execute(
                    "UPDATE translations SET status = ?, attempts = attempts + ?, error = ?, "
                    "updated_at = datetime('now') WHERE id = ?",
                    (FAILED, outcome.attempts, outcome.error, row["id"]),
                )
                failed += 1
            conn.execute(
                "UPDATE processing_jobs SET completed = ?, failed = ?, updated_at = datetime('now') WHERE id = ?",
                (completed, failed, job_id),
            )
        if progress:
            progress(done, len(pending))
        if outcome.fatal:
            aborted = outcome.error
            _reset_unstarted(conn, pending[done:])
            break

    with conn:
        conn.execute(
            "UPDATE processing_jobs SET status = ?, error = ?, finished_at = datetime('now'), "
            "updated_at = datetime('now') WHERE id = ?",
            ("failed" if aborted or failed else "done", aborted, job_id),
        )
    return RunSummary(total=len(pending), completed=completed, failed=failed, aborted=aborted)


def _reset_unstarted(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> None:
    """Chunks that were never reached stay (or return to) 'not started' so a later run picks them up."""
    with conn:
        for row in rows:
            conn.execute(
                "UPDATE translations SET status = ? WHERE id = ? AND status = ?", (NOT_STARTED, row["id"], PROCESSING)
            )


# --- overview and details ---------------------------------------------------------------------------------------


def _derive_status(counts: dict[str, int]) -> str:
    total = sum(counts.values())
    if total == 0:
        return NOT_STARTED
    if counts.get(FAILED):
        return FAILED
    if counts.get(APPROVED) == total:
        return APPROVED
    if counts.get(AWAITING_APPROVAL, 0) + counts.get(APPROVED, 0) == total:
        return AWAITING_APPROVAL
    if counts.get(NOT_STARTED) == total:
        return NOT_STARTED
    return IN_PROGRESS


def overview(conn: sqlite3.Connection, settings: Settings, book_id: int) -> list[ChapterProgress]:
    """Every chapter with its readiness and translation state for each chosen language."""
    targets = get_targets(conn, book_id)
    result: list[ChapterProgress] = []
    for chapter in chapter_service.list_chapters(conn, book_id):
        missing = _missing_pages(conn, book_id, chapter)
        item = ChapterProgress(
            id=chapter["id"],
            title=chapter["title"],
            order_index=chapter["order_index"],
            page_count=chapter["page_count"],
            approved_pages=chapter["approved_pages"],
            ready=not missing,
            missing_pages=missing[:MAX_LISTED_PAGES],
        )
        current_hashes = (
            [text_hash(c) for c in chapter_chunks(conn, settings, book_id, chapter)] if not missing else None
        )
        for code in targets:
            rows = conn.execute(
                "SELECT chunk_index, source_hash, status, notes, error, provider, translated_text, edited_text "
                "FROM translations WHERE chapter_id = ? AND language_code = ? ORDER BY chunk_index",
                (chapter["id"], code),
            ).fetchall()
            counts: dict[str, int] = {}
            for row in rows:
                counts[row["status"]] = counts.get(row["status"], 0) + 1
            keep = keep_unchanged_terms(conn, book_id, code) if rows else []
            wrong_language = sum(
                1
                for row in rows
                if untranslated_problem(
                    conn, book_id, code, row["edited_text"] or row["translated_text"], keep, row["provider"]
                )
            )
            progress = LanguageProgress(
                status=_derive_status(counts),
                total=len(rows),
                translated=counts.get(AWAITING_APPROVAL, 0) + counts.get(APPROVED, 0),
                approved=counts.get(APPROVED, 0),
                failed=counts.get(FAILED, 0),
                notes=sum(1 for row in rows if row["notes"]),
                test_output=any(row["provider"] == TEST_PROVIDER for row in rows),
                untranslated=wrong_language,
                error=next((row["error"] for row in rows if row["status"] == FAILED and row["error"]), None),
            )
            if rows and current_hashes is not None:
                progress.outdated = [row["source_hash"] for row in rows] != current_hashes
            item.languages[code] = progress
        result.append(item)
    return result


def list_chunks(conn: sqlite3.Connection, book_id: int, chapter_id: int, language: str) -> list[sqlite3.Row]:
    """The stored chunks (source and translation) of one chapter in one language, in order."""
    chapter_service.get_chapter(conn, book_id, chapter_id)
    return conn.execute(
        "SELECT chunk_index, source_text, translated_text, edited_text, status, notes, error, provider "
        "FROM translations WHERE chapter_id = ? AND language_code = ? ORDER BY chunk_index",
        (chapter_id, language),
    ).fetchall()
