"""HTTP routes for chapters and the glossary. All paths are under /api."""

import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.api.deps import get_conn, require_book, require_user
from app.services import chapters, glossary

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


class ChapterOut(BaseModel):
    id: int
    title: str
    heading: str
    order_index: int
    start_page: int
    end_page: int
    page_count: int
    read_pages: int
    approved_pages: int


class ChapterCreate(BaseModel):
    title: str = Field(max_length=300)
    heading: str = Field(default="", max_length=300)
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)


class ChapterUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    heading: str | None = Field(default=None, max_length=300)
    start_page: int | None = Field(default=None, ge=1)
    end_page: int | None = Field(default=None, ge=1)


class ChapterOrder(BaseModel):
    chapter_ids: list[int]


class ChapterPageOut(BaseModel):
    page_number: int
    review_status: str
    text: str


class ChaptersOut(BaseModel):
    chapters: list[ChapterOut]
    unassigned: list[tuple[int, int]]


class TermIn(BaseModel):
    source_term: str = Field(max_length=300)
    explanation: str = Field(default="", max_length=2000)
    author_notes: str = Field(default="", max_length=2000)
    keep_unchanged: bool = False
    translations: dict[str, str] = Field(default_factory=dict)


class TermOut(BaseModel):
    id: int
    source_term: str
    explanation: str
    author_notes: str
    keep_unchanged: bool
    translations: dict[str, str]


def _chapters_out(conn: sqlite3.Connection, book_id: int) -> ChaptersOut:
    return ChaptersOut(
        chapters=[ChapterOut(**dict(row)) for row in chapters.list_chapters(conn, book_id)],
        unassigned=chapters.unassigned_ranges(conn, book_id),
    )


@router.get("/books/{book_id}/chapters", response_model=ChaptersOut)
def list_chapters(
    book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> ChaptersOut:
    """Chapters in book order plus the page ranges not in any chapter."""
    return _chapters_out(conn, book["id"])


@router.post("/books/{book_id}/chapters", response_model=ChaptersOut, status_code=201)
def add_chapter(
    body: ChapterCreate, book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> ChaptersOut:
    """Add a chapter made of a page range."""
    chapters.create_chapter(
        conn, book["id"], title=body.title, heading=body.heading, start_page=body.start_page, end_page=body.end_page
    )
    return _chapters_out(conn, book["id"])


@router.post("/books/{book_id}/chapters/reorder", response_model=ChaptersOut)
def reorder(
    body: ChapterOrder, book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> ChaptersOut:
    """Set the order of all chapters."""
    chapters.reorder_chapters(conn, book["id"], body.chapter_ids)
    return _chapters_out(conn, book["id"])


@router.put("/books/{book_id}/chapters/{chapter_id}", response_model=ChaptersOut)
def edit_chapter(
    chapter_id: int,
    body: ChapterUpdate,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
) -> ChaptersOut:
    """Rename a chapter, change its heading or its page range."""
    chapters.update_chapter(
        conn,
        book["id"],
        chapter_id,
        title=body.title,
        heading=body.heading,
        start_page=body.start_page,
        end_page=body.end_page,
    )
    return _chapters_out(conn, book["id"])


@router.delete("/books/{book_id}/chapters/{chapter_id}", response_model=ChaptersOut)
def remove_chapter(
    chapter_id: int, book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> ChaptersOut:
    """Delete a chapter (its pages stay in the book)."""
    chapters.delete_chapter(conn, book["id"], chapter_id)
    return _chapters_out(conn, book["id"])


@router.get("/books/{book_id}/chapters/{chapter_id}/text", response_model=list[ChapterPageOut])
def chapter_preview(
    chapter_id: int, book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> list[ChapterPageOut]:
    """The chapter's pages with their current text, for preview."""
    return [
        ChapterPageOut(page_number=p.page_number, review_status=p.review_status, text=p.text)
        for p in chapters.chapter_pages(conn, book["id"], chapter_id)
    ]


@router.get("/books/{book_id}/chapters/{chapter_id}/export")
def export_chapter(
    chapter_id: int,
    approved_only: bool = False,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
) -> PlainTextResponse:
    """Download one chapter's text as a UTF-8 text file."""
    text = chapters.chapter_text(conn, book["id"], chapter_id, approved_only=approved_only)
    return PlainTextResponse(
        text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="book_{book["id"]}_chapter_{chapter_id}.txt"'},
    )


@router.get("/books/{book_id}/glossary", response_model=list[TermOut])
def list_terms(
    book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> list[TermOut]:
    """All glossary terms of the book."""
    return [TermOut(**vars(term)) for term in glossary.list_terms(conn, book["id"])]


@router.post("/books/{book_id}/glossary", response_model=TermOut, status_code=201)
def add_term(
    body: TermIn, book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> TermOut:
    """Add a glossary term."""
    term_id = glossary.create_term(conn, book["id"], **body.model_dump())
    return TermOut(**vars(glossary.get_term(conn, book["id"], term_id)))


@router.put("/books/{book_id}/glossary/{term_id}", response_model=TermOut)
def edit_term(
    term_id: int, body: TermIn, book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> TermOut:
    """Change a glossary term."""
    glossary.update_term(conn, book["id"], term_id, **body.model_dump())
    return TermOut(**vars(glossary.get_term(conn, book["id"], term_id)))


@router.delete("/books/{book_id}/glossary/{term_id}", status_code=204)
def remove_term(
    term_id: int, book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> None:
    """Delete a glossary term."""
    glossary.delete_term(conn, book["id"], term_id)
