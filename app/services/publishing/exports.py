"""Creating, listing and storing exported PDFs. Files get generated names and stay inside the book's exports folder."""

import json
import logging
import sqlite3
import threading
from pathlib import Path

from app.config import Settings
from app.db import connect
from app.services.publishing.model import Publication, PublishError, build_publication
from app.services.publishing.render import render_pdf
from app.storage import UnsafePathError, book_dir, safe_join

logger = logging.getLogger(__name__)

_threads: dict[int, threading.Thread] = {}
_lock = threading.Lock()


def is_running(book_id: int) -> bool:
    """True while a PDF for this book is being created."""
    thread = _threads.get(book_id)
    return thread is not None and thread.is_alive()


def _exports_dir(conn: sqlite3.Connection, settings: Settings, book_id: int) -> Path:
    book = conn.execute("SELECT uuid FROM books WHERE id = ?", (book_id,)).fetchone()
    if book is None:
        raise PublishError("That book no longer exists.")
    return safe_join(book_dir(settings.data_dir, book["uuid"]), "exports")


def _file_name(publication: Publication, export_id: int) -> str:
    parts = [publication.kind, *publication.languages]
    if publication.sample:
        parts.append("sample")
    return "-".join(parts + [str(export_id)]) + ".pdf"


def start_export(
    conn: sqlite3.Connection,
    settings: Settings,
    book_id: int,
    kind: str,
    languages: list[str] | None = None,
    *,
    toc: bool = True,
    page_references: bool = False,
    sample: bool = False,
    numbered_paragraphs: bool = True,
    background: bool = True,
) -> int:
    """Check that everything is approved, then create the PDF (in the background); returns the export id."""
    with _lock:
        if is_running(book_id):
            raise PublishError("A PDF is already being created for this book. Please wait for it to finish.")
        publication = build_publication(
            conn,
            settings,
            book_id,
            kind,
            languages,
            toc=toc,
            page_references=page_references,
            sample=sample,
            numbered_paragraphs=numbered_paragraphs,
        )
        options = json.dumps(
            {
                "toc": toc,
                "page_references": page_references,
                "sample": sample,
                "numbered_paragraphs": numbered_paragraphs,
            }
        )
        with conn:
            export_id = int(
                conn.execute(
                    "INSERT INTO export_jobs (book_id, export_type, languages, status, options) "
                    "VALUES (?, ?, ?, 'processing', ?)",
                    (book_id, kind, ",".join(publication.languages), options),
                ).lastrowid
            )
        if background:
            thread = threading.Thread(
                target=_run, args=(settings, book_id, export_id, publication), name=f"export-{book_id}", daemon=True
            )
            _threads[book_id] = thread
            thread.start()
    if not background:
        _run(settings, book_id, export_id, publication)
    return export_id


def _run(settings: Settings, book_id: int, export_id: int, publication: Publication) -> None:
    conn = connect(settings.database_path)
    try:
        data, pages = render_pdf(publication)
        folder = _exports_dir(conn, settings, book_id)
        folder.mkdir(exist_ok=True)
        name = _file_name(publication, export_id)
        path = safe_join(folder, name)
        path.write_bytes(data)
        with conn:
            conn.execute(
                "UPDATE export_jobs SET status = 'done', output_path = ?, file_name = ?, size_bytes = ?, "
                "page_count = ?, updated_at = datetime('now') WHERE id = ?",
                (str(path), name, len(data), pages, export_id),
            )
        logger.info("Created export id=%s book=%s pages=%s", export_id, book_id, pages)
    except Exception:
        logger.exception("Creating export id=%s failed", export_id)
        with conn:
            conn.execute(
                "UPDATE export_jobs SET status = 'failed', error = ?, updated_at = datetime('now') WHERE id = ?",
                ("Something went wrong while creating the PDF. Please try again.", export_id),
            )
    finally:
        conn.close()


def list_exports(conn: sqlite3.Connection, book_id: int) -> list[sqlite3.Row]:
    """The book's exports, newest first. Exports left 'processing' by a stopped server are marked failed."""
    if not is_running(book_id):
        with conn:
            conn.execute(
                "UPDATE export_jobs SET status = 'failed', error = 'The server stopped while this PDF was being "
                "created. Please create it again.' WHERE book_id = ? AND status = 'processing'",
                (book_id,),
            )
    return conn.execute(
        "SELECT id, export_type, languages, status, options, file_name, size_bytes, page_count, error, created_at "
        "FROM export_jobs WHERE book_id = ? ORDER BY id DESC",
        (book_id,),
    ).fetchall()


def _get(conn: sqlite3.Connection, book_id: int, export_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, status, file_name FROM export_jobs WHERE id = ? AND book_id = ?", (export_id, book_id)
    ).fetchone()
    if row is None:
        raise PublishError("That PDF was not found.")
    return row


def export_file(conn: sqlite3.Connection, settings: Settings, book_id: int, export_id: int) -> Path:
    """The PDF file of a finished export (only files inside the book's own exports folder are ever served)."""
    row = _get(conn, book_id, export_id)
    if row["status"] != "done" or not row["file_name"]:
        raise PublishError("This PDF is not ready.")
    try:
        path = safe_join(_exports_dir(conn, settings, book_id), Path(row["file_name"]).name)
    except UnsafePathError as exc:
        raise PublishError("That PDF is not available.") from exc
    if not path.is_file():
        raise PublishError("The PDF file is missing. Please create it again.")
    return path


def delete_export(conn: sqlite3.Connection, settings: Settings, book_id: int, export_id: int) -> None:
    """Remove an export and its file."""
    row = _get(conn, book_id, export_id)
    if row["status"] == "processing" and is_running(book_id):
        raise PublishError("This PDF is still being created.")
    if row["file_name"]:
        try:
            safe_join(_exports_dir(conn, settings, book_id), Path(row["file_name"]).name).unlink(missing_ok=True)
        except UnsafePathError:
            logger.warning("Ignoring unsafe export file name for export=%s", export_id)
    with conn:
        conn.execute("DELETE FROM export_jobs WHERE id = ?", (export_id,))
