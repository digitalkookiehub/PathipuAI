"""Translation review: the author reads, corrects and approves each translated part.

The machine translation (translated_text) is never changed. The author's edits live in edited_text, and the text
that counts is COALESCE(edited_text, translated_text). Any change sends a part back to 'awaiting approval'; only
the author's explicit action approves it.
"""

import logging
import sqlite3

from app.config import Settings
from app.services import chapters as chapter_service
from app.services.translation import service as tr
from app.services.translation.chunking import text_hash

logger = logging.getLogger(__name__)


class ReviewBlocked(tr.TranslationError):
    """The part cannot be approved or edited right now; the message says why and what to do."""


def current_text(row: sqlite3.Row) -> str:
    """The text the author sees: their edit if there is one, otherwise the machine translation."""
    if row["edited_text"] is not None:
        return row["edited_text"]
    return row["translated_text"] or ""


def get_chunk(conn: sqlite3.Connection, book_id: int, chapter_id: int, language: str, index: int) -> sqlite3.Row:
    """One stored part of a chapter's translation, or TranslationError."""
    chapter_service.get_chapter(conn, book_id, chapter_id)
    row = conn.execute(
        "SELECT id, chunk_index, source_text, source_hash, translated_text, edited_text, status, notes, error, "
        "provider FROM translations WHERE chapter_id = ? AND language_code = ? AND chunk_index = ?",
        (chapter_id, language, index),
    ).fetchone()
    if row is None:
        raise tr.TranslationError("That part of the translation was not found.")
    return row


def untranslated_indexes(conn: sqlite3.Connection, book_id: int, chapter_id: int, language: str) -> set[int]:
    """Parts whose current text is not in the target language (for example still in Tamil)."""
    keep = tr.keep_unchanged_terms(conn, book_id, language)
    rows = conn.execute(
        "SELECT chunk_index, translated_text, edited_text, provider FROM translations "
        "WHERE chapter_id = ? AND language_code = ?",
        (chapter_id, language),
    )
    return {
        row["chunk_index"]
        for row in rows
        if tr.untranslated_problem(
            conn, book_id, language, row["edited_text"] or row["translated_text"], keep, row["provider"]
        )
    }


def outdated_indexes(conn: sqlite3.Connection, settings: Settings, book_id: int, chapter_id: int) -> set[int]:
    """Parts whose Tamil source no longer matches the chapter's approved text."""
    chapter = chapter_service.get_chapter(conn, book_id, chapter_id)
    current = [text_hash(chunk) for chunk in tr.chapter_chunks(conn, settings, book_id, chapter)]
    return {
        row["chunk_index"]
        for row in conn.execute(
            "SELECT chunk_index, source_hash FROM translations WHERE chapter_id = ? AND source_hash IS NOT NULL",
            (chapter_id,),
        )
        if row["chunk_index"] >= len(current) or row["source_hash"] != current[row["chunk_index"]]
    }


def _log(conn: sqlite3.Connection, row_id: int, old: str | None, new: str | None, action: str) -> None:
    conn.execute(
        "INSERT INTO text_history (entity_type, entity_id, old_text, new_text, action) "
        "VALUES ('translation', ?, ?, ?, ?)",
        (row_id, old, new, action),
    )


def _require_translated(row: sqlite3.Row) -> None:
    if row["status"] not in (tr.AWAITING_APPROVAL, tr.APPROVED) or row["translated_text"] is None:
        raise ReviewBlocked("This part has not been translated yet.")


def _approval_problem(row: sqlite3.Row, outdated: bool, wrong_language: str | None = None) -> str | None:
    """Why the part cannot be approved, or None."""
    if row["status"] not in (tr.AWAITING_APPROVAL, tr.APPROVED) or row["translated_text"] is None:
        return "This part has not been translated yet."
    if row["provider"] == tr.TEST_PROVIDER:
        return (
            "This is test-mode placeholder text, not a translation. Translate the chapter with the real provider first."
        )
    if outdated:
        return "The Tamil text changed after this part was translated. Translate the chapter again first."
    if not current_text(row).strip():
        return "The translation is empty."
    if wrong_language:
        return wrong_language + " Translate it again, or write the translation yourself."
    return None


def save_edit(
    conn: sqlite3.Connection, settings: Settings, book_id: int, chapter_id: int, language: str, index: int, text: str
) -> str:
    """Save the author's wording; returns the part's status (a changed part must be approved again)."""
    row = get_chunk(conn, book_id, chapter_id, language, index)
    _require_translated(row)
    if not text.strip():
        raise ReviewBlocked("A translation cannot be empty. Use 'Back to the machine translation' to undo your edits.")
    if text == current_text(row):
        return row["status"]
    edited = None if text == row["translated_text"] else text
    entries = tr._entries_for(conn, book_id, language, row["source_text"])
    with conn:
        conn.execute(
            "UPDATE translations SET edited_text = ?, status = ?, approved_at = NULL, notes = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (edited, tr.AWAITING_APPROVAL, tr._glossary_notes(entries, text), row["id"]),
        )
        _log(conn, row["id"], current_text(row), text, "translation_edit")
    logger.info("Edited translation book=%s chapter=%s lang=%s part=%s", book_id, chapter_id, language, index)
    return tr.AWAITING_APPROVAL


def approve_chunk(
    conn: sqlite3.Connection, settings: Settings, book_id: int, chapter_id: int, language: str, index: int
) -> None:
    """Approve one part's current text. Refused for placeholders, outdated parts and untranslated parts."""
    row = get_chunk(conn, book_id, chapter_id, language, index)
    wrong = tr.untranslated_problem(conn, book_id, language, current_text(row), provider=row["provider"])
    problem = _approval_problem(row, index in outdated_indexes(conn, settings, book_id, chapter_id), wrong)
    if problem:
        raise ReviewBlocked(problem)
    with conn:
        conn.execute(
            "UPDATE translations SET status = ?, approved_at = datetime('now'), updated_at = datetime('now') "
            "WHERE id = ?",
            (tr.APPROVED, row["id"]),
        )
        _log(conn, row["id"], None, current_text(row), "translation_approve")


def restore_machine(
    conn: sqlite3.Connection, settings: Settings, book_id: int, chapter_id: int, language: str, index: int
) -> None:
    """Drop the author's edits and go back to the machine translation (it needs approval again)."""
    row = get_chunk(conn, book_id, chapter_id, language, index)
    _require_translated(row)
    if row["edited_text"] is None and row["status"] != tr.APPROVED:
        return
    entries = tr._entries_for(conn, book_id, language, row["source_text"])
    with conn:
        conn.execute(
            "UPDATE translations SET edited_text = NULL, status = ?, approved_at = NULL, notes = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (tr.AWAITING_APPROVAL, tr._glossary_notes(entries, row["translated_text"]), row["id"]),
        )
        _log(conn, row["id"], current_text(row), row["translated_text"], "translation_restore")


def approve_all(
    conn: sqlite3.Connection, settings: Settings, book_id: int, chapter_id: int, language: str
) -> tuple[int, int]:
    """Approve every part of the chapter that can be approved; returns (approved, skipped).

    Skipped parts are placeholders, outdated, failed or not translated yet. This is an explicit author action.
    """
    chapter_service.get_chapter(conn, book_id, chapter_id)
    outdated = outdated_indexes(conn, settings, book_id, chapter_id)
    keep = tr.keep_unchanged_terms(conn, book_id, language)
    rows = conn.execute(
        "SELECT id, chunk_index, translated_text, edited_text, status, provider FROM translations "
        "WHERE chapter_id = ? AND language_code = ? ORDER BY chunk_index",
        (chapter_id, language),
    ).fetchall()
    approved = skipped = 0
    with conn:
        for row in rows:
            if row["status"] == tr.APPROVED:
                continue
            wrong = tr.untranslated_problem(conn, book_id, language, current_text(row), keep, row["provider"])
            if _approval_problem(row, row["chunk_index"] in outdated, wrong):
                skipped += 1
                continue
            conn.execute(
                "UPDATE translations SET status = ?, approved_at = datetime('now'), updated_at = datetime('now') "
                "WHERE id = ?",
                (tr.APPROVED, row["id"]),
            )
            _log(conn, row["id"], None, current_text(row), "translation_approve")
            approved += 1
    return approved, skipped
