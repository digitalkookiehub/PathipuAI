"""Chapter management: manual chapters made of page ranges, in a chosen order."""

import sqlite3
from dataclasses import dataclass

from app.services.books import BookError


class ChapterError(BookError):
    """A chapter problem the author can fix; the message is safe to show them."""


@dataclass(frozen=True)
class ChapterPage:
    """One page of a chapter with its current (corrected) text."""

    page_number: int
    review_status: str
    text: str


def _book_page_count(conn: sqlite3.Connection, book_id: int) -> int:
    row = conn.execute("SELECT page_count FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise ChapterError("That book no longer exists.")
    return int(row["page_count"])


def _validate_range(conn: sqlite3.Connection, book_id: int, start: int, end: int, ignore_id: int | None) -> None:
    page_count = _book_page_count(conn, book_id)
    if start < 1 or end > page_count:
        raise ChapterError(f"Pages must be between 1 and {page_count}.")
    if start > end:
        raise ChapterError("The first page must not be after the last page.")
    clash = conn.execute(
        "SELECT title, start_page, end_page FROM chapters WHERE book_id = ? AND id != ? "
        "AND start_page <= ? AND end_page >= ? ORDER BY order_index LIMIT 1",
        (book_id, ignore_id or 0, end, start),
    ).fetchone()
    if clash:
        raise ChapterError(
            f'Pages {clash["start_page"]}-{clash["end_page"]} already belong to the chapter "{clash["title"]}".'
        )


def list_chapters(conn: sqlite3.Connection, book_id: int) -> list[sqlite3.Row]:
    """Chapters in book order, with how many of their pages are read and approved."""
    return conn.execute(
        "SELECT c.id, c.title, c.heading, c.order_index, c.start_page, c.end_page, "
        "c.end_page - c.start_page + 1 AS page_count, "
        "(SELECT COUNT(*) FROM book_pages p WHERE p.book_id = c.book_id AND p.page_number BETWEEN c.start_page "
        "AND c.end_page AND p.ocr_status = 'done') AS read_pages, "
        "(SELECT COUNT(*) FROM book_pages p WHERE p.book_id = c.book_id AND p.page_number BETWEEN c.start_page "
        "AND c.end_page AND p.review_status = 'approved') AS approved_pages "
        "FROM chapters c WHERE c.book_id = ? ORDER BY c.order_index, c.id",
        (book_id,),
    ).fetchall()


def get_chapter(conn: sqlite3.Connection, book_id: int, chapter_id: int) -> sqlite3.Row:
    """Return one chapter of the book or raise ChapterError."""
    for row in list_chapters(conn, book_id):
        if row["id"] == chapter_id:
            return row
    raise ChapterError("That chapter was not found.")


def create_chapter(
    conn: sqlite3.Connection, book_id: int, *, title: str, start_page: int, end_page: int, heading: str = ""
) -> int:
    """Add a chapter at the end of the book order; returns its id."""
    title = title.strip()
    if not title:
        raise ChapterError("Please enter a chapter title.")
    _validate_range(conn, book_id, start_page, end_page, None)
    with conn:
        next_order = conn.execute(
            "SELECT COALESCE(MAX(order_index), 0) + 1 FROM chapters WHERE book_id = ?", (book_id,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO chapters (book_id, title, heading, order_index, start_page, end_page) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (book_id, title, heading.strip(), next_order, start_page, end_page),
        )
    return int(cur.lastrowid)


def update_chapter(
    conn: sqlite3.Connection,
    book_id: int,
    chapter_id: int,
    *,
    title: str | None = None,
    heading: str | None = None,
    start_page: int | None = None,
    end_page: int | None = None,
) -> None:
    """Change any of a chapter's title, heading or page range."""
    chapter = get_chapter(conn, book_id, chapter_id)
    new_title = chapter["title"] if title is None else title.strip()
    if not new_title:
        raise ChapterError("Please enter a chapter title.")
    new_start = chapter["start_page"] if start_page is None else start_page
    new_end = chapter["end_page"] if end_page is None else end_page
    _validate_range(conn, book_id, new_start, new_end, chapter_id)
    with conn:
        conn.execute(
            "UPDATE chapters SET title = ?, heading = ?, start_page = ?, end_page = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (new_title, chapter["heading"] if heading is None else heading.strip(), new_start, new_end, chapter_id),
        )


def delete_chapter(conn: sqlite3.Connection, book_id: int, chapter_id: int) -> None:
    """Remove a chapter (its pages stay in the book)."""
    get_chapter(conn, book_id, chapter_id)
    with conn:
        conn.execute("DELETE FROM chapters WHERE id = ?", (chapter_id,))


def reorder_chapters(conn: sqlite3.Connection, book_id: int, ordered_ids: list[int]) -> None:
    """Set the book order of chapters; ordered_ids must list every chapter exactly once."""
    existing = [row["id"] for row in list_chapters(conn, book_id)]
    if sorted(ordered_ids) != sorted(existing):
        raise ChapterError("The chapter list changed. Please reload the page and try again.")
    with conn:
        for position, chapter_id in enumerate(ordered_ids, start=1):
            conn.execute("UPDATE chapters SET order_index = ? WHERE id = ?", (position, chapter_id))


def unassigned_ranges(conn: sqlite3.Connection, book_id: int) -> list[tuple[int, int]]:
    """Page ranges that are not part of any chapter yet."""
    page_count = _book_page_count(conn, book_id)
    covered = [False] * (page_count + 2)
    for row in conn.execute("SELECT start_page, end_page FROM chapters WHERE book_id = ?", (book_id,)):
        for page in range(row["start_page"], row["end_page"] + 1):
            covered[page] = True
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for page in range(1, page_count + 2):
        if page <= page_count and not covered[page]:
            start = page if start is None else start
        elif start is not None:
            ranges.append((start, page - 1))
            start = None
    return ranges


def chapter_pages(
    conn: sqlite3.Connection, book_id: int, chapter_id: int, *, approved_only: bool = False
) -> list[ChapterPage]:
    """The chapter's read pages in page order, using corrected text where it exists."""
    chapter = get_chapter(conn, book_id, chapter_id)
    query = (
        "SELECT page_number, review_status, COALESCE(corrected_text, ocr_text, '') AS text FROM book_pages "
        "WHERE book_id = ? AND page_number BETWEEN ? AND ? AND ocr_status = 'done'"
    )
    if approved_only:
        query += " AND review_status = 'approved'"
    rows = conn.execute(query + " ORDER BY page_number", (book_id, chapter["start_page"], chapter["end_page"]))
    return [ChapterPage(r["page_number"], r["review_status"], r["text"]) for r in rows]


def chapter_text(conn: sqlite3.Connection, book_id: int, chapter_id: int, *, approved_only: bool = False) -> str:
    """The chapter as one text with a heading line and a marker before each page."""
    chapter = get_chapter(conn, book_id, chapter_id)
    pages = chapter_pages(conn, book_id, chapter_id, approved_only=approved_only)
    heading = chapter["heading"] or chapter["title"]
    body = "\n\n".join(f"--- Page {p.page_number} ---\n{p.text}" for p in pages)
    return f"{heading}\n\n{body}" if body else heading
