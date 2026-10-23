"""OCR review: corrections, approval, search and text export.

Original OCR text (ocr_text) is never changed. The author's edits live in corrected_text, and the text
used downstream is COALESCE(corrected_text, ocr_text). Review status is pending / corrected / approved.
"""

import logging
import sqlite3
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PENDING = "pending"
CORRECTED = "corrected"
APPROVED = "approved"
SNIPPET_RADIUS = 40


class ReviewError(Exception):
    """A problem the author can understand; the message is safe to show them."""


@dataclass(frozen=True)
class SearchHit:
    """One page matching a search."""

    page_number: int
    snippet: str


def get_page(conn: sqlite3.Connection, book_id: int, page_number: int) -> sqlite3.Row | None:
    """Return one page's review data, or None if it does not exist."""
    return conn.execute(
        "SELECT id, page_number, image_path, ocr_text, corrected_text, ocr_status, review_status, "
        "ocr_confidence, ocr_engine, error, approved_at FROM book_pages WHERE book_id = ? AND page_number = ?",
        (book_id, page_number),
    ).fetchone()


def current_text(page: sqlite3.Row) -> str:
    """The text the author sees: their correction if there is one, otherwise the OCR text."""
    if page["corrected_text"] is not None:
        return page["corrected_text"]
    return page["ocr_text"] or ""


def _require_page(conn: sqlite3.Connection, book_id: int, page_number: int) -> sqlite3.Row:
    page = get_page(conn, book_id, page_number)
    if page is None:
        raise ReviewError("That page does not exist.")
    if page["ocr_status"] != "done":
        raise ReviewError("This page has not been read yet, so there is nothing to review.")
    return page


def _log_history(conn: sqlite3.Connection, page_id: int, old: str | None, new: str | None, action: str) -> None:
    conn.execute(
        "INSERT INTO text_history (entity_type, entity_id, old_text, new_text, action) VALUES ('page', ?, ?, ?, ?)",
        (page_id, old, new, action),
    )


def save_corrected_text(conn: sqlite3.Connection, book_id: int, page_number: int, text: str) -> str:
    """Save the author's text and return the page's new review status.

    Any change resets approval: the page becomes 'corrected' (or 'pending' if the text matches the
    original OCR again) and must be approved again.
    """
    page = _require_page(conn, book_id, page_number)
    if text == current_text(page):
        return page["review_status"]
    status = PENDING if text == (page["ocr_text"] or "") else CORRECTED
    with conn:
        conn.execute(
            "UPDATE book_pages SET corrected_text = ?, review_status = ?, approved_at = NULL, "
            "updated_at = datetime('now') WHERE id = ?",
            (text, status, page["id"]),
        )
        _log_history(conn, page["id"], current_text(page), text, "edit")
    _refresh_book_status(conn, book_id)
    logger.info("Saved correction book=%s page=%s", book_id, page_number)
    return status


def approve_page(conn: sqlite3.Connection, book_id: int, page_number: int) -> None:
    """Approve the page's current text. Only the author's explicit action approves a page."""
    page = _require_page(conn, book_id, page_number)
    with conn:
        conn.execute(
            "UPDATE book_pages SET review_status = ?, approved_at = datetime('now'), "
            "updated_at = datetime('now') WHERE id = ?",
            (APPROVED, page["id"]),
        )
        _log_history(conn, page["id"], None, current_text(page), "approve")
    _refresh_book_status(conn, book_id)
    logger.info("Approved book=%s page=%s", book_id, page_number)


def approve_range(conn: sqlite3.Connection, book_id: int, first_page: int, last_page: int) -> tuple[int, int]:
    """Approve every read page in a range that is not approved yet.

    Returns (pages approved, pages skipped because they have not been read). This is an explicit author
    action; nothing is ever approved automatically from OCR confidence.
    """
    book = conn.execute("SELECT page_count FROM books WHERE id = ?", (book_id,)).fetchone()
    if book is None:
        raise ReviewError("That book no longer exists.")
    if first_page < 1 or last_page > book["page_count"]:
        raise ReviewError(f"Pages must be between 1 and {book['page_count']}.")
    if first_page > last_page:
        raise ReviewError("The first page must not be after the last page.")
    rows = conn.execute(
        "SELECT id, page_number, ocr_status, review_status, ocr_text, corrected_text FROM book_pages "
        "WHERE book_id = ? AND page_number BETWEEN ? AND ?",
        (book_id, first_page, last_page),
    ).fetchall()
    unread = sum(1 for row in rows if row["ocr_status"] != "done")
    to_approve = [row for row in rows if row["ocr_status"] == "done" and row["review_status"] != APPROVED]
    with conn:
        for row in to_approve:
            conn.execute(
                "UPDATE book_pages SET review_status = ?, approved_at = datetime('now'), "
                "updated_at = datetime('now') WHERE id = ?",
                (APPROVED, row["id"]),
            )
            text = row["corrected_text"] if row["corrected_text"] is not None else row["ocr_text"]
            _log_history(conn, row["id"], None, text, "approve")
    _refresh_book_status(conn, book_id)
    logger.info("Approved %s pages in book=%s range=%s-%s", len(to_approve), book_id, first_page, last_page)
    return len(to_approve), unread


def restore_original(conn: sqlite3.Connection, book_id: int, page_number: int) -> None:
    """Throw away the author's edits and go back to the original OCR text (needs approval again)."""
    page = _require_page(conn, book_id, page_number)
    if page["corrected_text"] is None and page["review_status"] == PENDING:
        return
    with conn:
        conn.execute(
            "UPDATE book_pages SET corrected_text = NULL, review_status = ?, approved_at = NULL, "
            "updated_at = datetime('now') WHERE id = ?",
            (PENDING, page["id"]),
        )
        _log_history(conn, page["id"], current_text(page), page["ocr_text"], "restore_original")
    _refresh_book_status(conn, book_id)


def review_counts(conn: sqlite3.Connection, book_id: int) -> dict[str, int]:
    """Count read pages by review status (pending / corrected / approved)."""
    counts = {PENDING: 0, CORRECTED: 0, APPROVED: 0}
    for row in conn.execute(
        "SELECT review_status, COUNT(*) AS n FROM book_pages WHERE book_id = ? AND ocr_status = 'done' "
        "GROUP BY review_status",
        (book_id,),
    ):
        counts[row["review_status"]] = row["n"]
    return counts


def _refresh_book_status(conn: sqlite3.Connection, book_id: int) -> None:
    """Update the book's overall status after review changes (only once OCR is finished)."""
    book = conn.execute("SELECT status FROM books WHERE id = ?", (book_id,)).fetchone()
    if book is None or book["status"] not in ("needs_correction", "awaiting_approval", "approved"):
        return
    total = conn.execute("SELECT COUNT(*) FROM book_pages WHERE book_id = ?", (book_id,)).fetchone()[0]
    counts = review_counts(conn, book_id)
    if total and counts[APPROVED] == total:
        status = "approved"
    elif counts[APPROVED] or counts[CORRECTED]:
        status = "awaiting_approval"
    else:
        status = "needs_correction"
    with conn:
        conn.execute("UPDATE books SET status = ?, updated_at = datetime('now') WHERE id = ?", (status, book_id))


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_text(conn: sqlite3.Connection, book_id: int, query: str, limit: int = 50) -> list[SearchHit]:
    """Find pages whose current text contains the query; return page numbers with a short snippet."""
    query = query.strip()
    if not query:
        return []
    rows = conn.execute(
        "SELECT page_number, COALESCE(corrected_text, ocr_text, '') AS text FROM book_pages "
        "WHERE book_id = ? AND ocr_status = 'done' "
        "AND COALESCE(corrected_text, ocr_text, '') LIKE ? ESCAPE '\\' ORDER BY page_number LIMIT ?",
        (book_id, f"%{_escape_like(query)}%", limit),
    ).fetchall()
    hits: list[SearchHit] = []
    for row in rows:
        text = row["text"]
        index = max(text.lower().find(query.lower()), 0)
        start = max(index - SNIPPET_RADIUS, 0)
        snippet = text[start : index + len(query) + SNIPPET_RADIUS].replace("\n", " ")
        hits.append(SearchHit(page_number=row["page_number"], snippet=snippet))
    return hits


def export_source_text(conn: sqlite3.Connection, book_id: int, *, approved_only: bool = False) -> str:
    """Return the corrected source text for all read pages, with a marker line before each page."""
    query = "SELECT page_number, COALESCE(corrected_text, ocr_text, '') AS text FROM book_pages "
    query += "WHERE book_id = ? AND ocr_status = 'done'"
    if approved_only:
        query += " AND review_status = 'approved'"
    parts = [
        f"--- Page {row['page_number']} ---\n{row['text']}"
        for row in conn.execute(query + " ORDER BY page_number", (book_id,))
    ]
    return "\n\n".join(parts)
