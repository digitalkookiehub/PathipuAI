"""Book management: create, list, fetch and delete books."""

import logging
import shutil
import sqlite3
from pathlib import Path

from app.config import SUPPORTED_LANGUAGES, Settings
from app.services.pdf_validation import has_enough_disk, validate_pdf
from app.storage import book_dir, create_book_dirs, new_book_uuid

logger = logging.getLogger(__name__)

STATUS_LABELS: dict[str, str] = {
    "not_started": "Not started",
    "processing": "Processing",
    "needs_correction": "Needs correction",
    "awaiting_approval": "Awaiting approval",
    "approved": "Approved",
    "failed": "Failed",
}


class BookError(Exception):
    """A problem the author can fix; the message is safe to show them."""


def create_book(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    title: str,
    author: str,
    description: str,
    source_language: str,
    publication_details: str,
    pdf_bytes: bytes,
) -> int:
    """Validate and store a new book with its original PDF; return the book id."""
    title = title.strip()
    author = author.strip()
    if not title:
        raise BookError("Please enter the book title.")
    if source_language not in SUPPORTED_LANGUAGES:
        raise BookError("Please choose a supported source language.")
    exists = conn.execute(
        "SELECT 1 FROM books WHERE lower(title) = lower(?) AND lower(author) = lower(?)",
        (title, author),
    ).fetchone()
    if exists:
        raise BookError("A book with this title and author already exists. Open it from the dashboard instead.")

    result = validate_pdf(pdf_bytes, settings.max_upload_mb, settings.max_pages)
    if not result.ok:
        raise BookError(result.message)
    if not has_enough_disk(settings.data_dir, settings.min_free_disk_mb + len(pdf_bytes) // (1024 * 1024)):
        raise BookError("There is not enough free disk space on the server to store this book.")

    book_uuid = new_book_uuid()
    root = create_book_dirs(settings.data_dir, book_uuid)
    pdf_path = root / "original.pdf"
    try:
        pdf_path.write_bytes(pdf_bytes)
        with conn:
            cur = conn.execute(
                "INSERT INTO books (uuid, title, author, description, source_language, "
                "publication_details, original_pdf_path, page_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    book_uuid,
                    title,
                    author,
                    description.strip(),
                    source_language,
                    publication_details.strip(),
                    str(pdf_path),
                    result.page_count,
                ),
            )
            book_id = int(cur.lastrowid)
            conn.executemany(
                "INSERT INTO book_pages (book_id, page_number) VALUES (?, ?)",
                [(book_id, n) for n in range(1, result.page_count + 1)],
            )
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        logger.exception("Creating book failed")
        raise
    logger.info("Created book id=%s pages=%s", book_id, result.page_count)
    return book_id


def list_books(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all books, newest first."""
    return conn.execute(
        "SELECT id, title, author, source_language, page_count, status, created_at "
        "FROM books ORDER BY created_at DESC, id DESC"
    ).fetchall()


def get_book(conn: sqlite3.Connection, book_id: int) -> sqlite3.Row | None:
    """Return one book or None."""
    return conn.execute(
        "SELECT id, uuid, title, author, description, source_language, publication_details, "
        "original_pdf_path, page_count, status, created_at FROM books WHERE id = ?",
        (book_id,),
    ).fetchone()


def delete_book(conn: sqlite3.Connection, settings: Settings, book_id: int) -> None:
    """Delete a book's records and files. Callers must obtain confirmation first."""
    book = get_book(conn, book_id)
    if book is None:
        raise BookError("That book no longer exists.")
    root: Path = book_dir(settings.data_dir, book["uuid"])
    with conn:
        conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
    shutil.rmtree(root, ignore_errors=True)
    logger.info("Deleted book id=%s", book_id)
