"""HTTP routes for books, OCR and review. All paths are under /api."""

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from app.api import jobs
from app.api.deps import get_conn, get_settings, require_book, require_user
from app.api.schemas import (
    AccuracyOut,
    ApproveRangeRequest,
    BookOut,
    EngineAccuracyOut,
    LanguageOut,
    OcrJobOut,
    OcrStartRequest,
    OcrStatusOut,
    PageDetail,
    PageSummary,
    RereadRequest,
    SearchHitOut,
    TextUpdate,
)
from app.config import SUPPORTED_LANGUAGES, Settings
from app.services import review
from app.services.accuracy import AccuracyReport, book_ocr_accuracy
from app.services.books import STATUS_LABELS, BookError, create_book, delete_book, list_books
from app.services.lexicon import book_lexicon
from app.services.ocr import (
    OcrSetupError,
    check_engine,
    check_language,
    engine_status,
    page_status_counts,
    reset_pages_for_reread,
)
from app.storage import UnsafePathError, book_dir, safe_join

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


def _accuracy_out(report: AccuracyReport) -> AccuracyOut:
    return AccuracyOut(
        pages=report.pages,
        error_rate=report.error_rate,
        by_engine={name: EngineAccuracyOut(**vars(acc)) for name, acc in report.by_engine.items()},
    )


def _book_out(row: sqlite3.Row) -> BookOut:
    code = row["source_language"]
    return BookOut(
        id=row["id"],
        title=row["title"],
        author=row["author"],
        description=row["description"] if "description" in row.keys() else "",
        source_language=code,
        source_language_name=SUPPORTED_LANGUAGES.get(code, (code, ""))[0],
        publication_details=row["publication_details"] if "publication_details" in row.keys() else "",
        page_count=row["page_count"],
        status=row["status"],
        status_label=STATUS_LABELS.get(row["status"], row["status"]),
        created_at=row["created_at"],
    )


@router.get("/languages", response_model=list[LanguageOut])
def languages() -> list[LanguageOut]:
    """Languages the app supports."""
    return [LanguageOut(code=code, name=name) for code, (name, _tess) in SUPPORTED_LANGUAGES.items()]


@router.get("/books", response_model=list[BookOut])
def books(conn: sqlite3.Connection = Depends(get_conn)) -> list[BookOut]:
    """List all books, newest first."""
    return [_book_out(row) for row in list_books(conn)]


@router.post("/books", response_model=BookOut, status_code=201)
def add_book(
    title: str = Form(...),
    author: str = Form(""),
    description: str = Form(""),
    source_language: str = Form("ta"),
    publication_details: str = Form(""),
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> BookOut:
    """Create a book from an uploaded scanned PDF."""
    limit = settings.max_upload_mb * 1024 * 1024 + 1
    data = file.file.read(limit)  # one byte over the limit is enough to reject it
    book_id = create_book(
        conn,
        settings,
        title=title,
        author=author,
        description=description,
        source_language=source_language,
        publication_details=publication_details,
        pdf_bytes=data,
    )
    return _book_out(require_book(book_id, conn))


@router.get("/books/{book_id}", response_model=BookOut)
def book_detail(book: sqlite3.Row = Depends(require_book)) -> BookOut:
    """One book's details."""
    return _book_out(book)


@router.delete("/books/{book_id}", status_code=204)
def remove_book(
    confirm: bool = False,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> None:
    """Delete a book and its files. Requires confirm=true."""
    if not confirm:
        raise BookError("Please confirm that you want to delete this book.")
    if jobs.is_running(book["id"]):
        raise BookError("This book is being read right now. Please wait until it finishes.")
    delete_book(conn, settings, book["id"])


@router.get("/ocr/ready", response_model=dict[str, object])
def ocr_ready(language: str = "ta", settings: Settings = Depends(get_settings)) -> dict[str, object]:
    """Whether Tesseract and the language data are available."""
    try:
        check_language(settings, language)
    except OcrSetupError as exc:
        return {"ready": False, "message": str(exc)}
    return {"ready": True, "message": None}


@router.get("/books/{book_id}/ocr", response_model=OcrStatusOut)
def ocr_status(
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> OcrStatusOut:
    """Progress of reading (OCR) and review for a book; poll this while a job runs."""
    ready, message = True, None
    try:
        check_language(settings, book["source_language"])
    except OcrSetupError as exc:
        ready, message = False, str(exc)
    row = conn.execute(
        "SELECT status, total, completed, failed FROM processing_jobs "
        "WHERE book_id = ? AND job_type = 'ocr' ORDER BY id DESC LIMIT 1",
        (book["id"],),
    ).fetchone()
    return OcrStatusOut(
        running=jobs.is_running(book["id"]),
        error=jobs.last_error(book["id"]),
        ready=ready,
        ready_message=message,
        page_counts=page_status_counts(conn, book["id"]),
        review_counts=review.review_counts(conn, book["id"]),
        job=OcrJobOut(**dict(row)) if row else None,
        accuracy=_accuracy_out(book_ocr_accuracy(conn, book["id"])),
        engines=engine_status(settings, book["source_language"]),
    )


@router.post("/books/{book_id}/ocr", status_code=202)
def start_ocr(
    body: OcrStartRequest,
    book: sqlite3.Row = Depends(require_book),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Start reading pages in the background."""
    _check_range(body.first_page, body.last_page, book["page_count"])
    check_engine(settings, book["source_language"], body.engine)
    jobs.start_ocr(
        settings,
        book["id"],
        first_page=body.first_page,
        last_page=body.last_page,
        retry_failed=body.retry_failed,
        engine=body.engine,
    )
    return {"status": "started"}


@router.post("/books/{book_id}/ocr/reread", status_code=202)
def reread(
    body: RereadRequest,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> dict[str, int | str]:
    """Reset a page range and read it again."""
    _check_range(body.first_page, body.last_page, book["page_count"])
    if jobs.is_running(book["id"]):
        raise OcrSetupError("This book is already being read. Please wait for it to finish.")
    check_engine(settings, book["source_language"], body.engine)
    reset = reset_pages_for_reread(
        conn, book["id"], body.first_page, body.last_page, discard_corrections=body.discard_corrections
    )
    jobs.start_ocr(
        settings,
        book["id"],
        first_page=body.first_page,
        last_page=body.last_page,
        retry_failed=False,
        engine=body.engine,
    )
    return {"status": "started", "pages": reset}


def _check_range(first: int | None, last: int | None, page_count: int) -> None:
    for value in (first, last):
        if value is not None and value > page_count:
            raise BookError(f"This book has only {page_count} pages.")
    if first is not None and last is not None and first > last:
        raise BookError("'From page' must not be after 'To page'.")


@router.get("/books/{book_id}/pages", response_model=list[PageSummary])
def pages(book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)) -> list[PageSummary]:
    """Status of every page."""
    rows = conn.execute(
        "SELECT page_number, ocr_status, review_status, ocr_confidence FROM book_pages "
        "WHERE book_id = ? ORDER BY page_number",
        (book["id"],),
    ).fetchall()
    return [PageSummary(**dict(row)) for row in rows]


def _page_or_404(conn: sqlite3.Connection, book_id: int, page_number: int) -> sqlite3.Row:
    page = review.get_page(conn, book_id, page_number)
    if page is None:
        raise HTTPException(status_code=404, detail="That page was not found.")
    return page


def _page_detail(page: sqlite3.Row) -> PageDetail:
    return PageDetail(
        page_number=page["page_number"],
        ocr_status=page["ocr_status"],
        review_status=page["review_status"],
        ocr_confidence=page["ocr_confidence"],
        ocr_text=page["ocr_text"] or "",
        corrected_text=page["corrected_text"],
        text=review.current_text(page),
        error=page["error"],
        has_image=bool(page["image_path"]),
        ocr_engine=page["ocr_engine"],
    )


@router.get("/books/{book_id}/pages/{page_number}", response_model=PageDetail)
def page_detail(
    page_number: int, book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> PageDetail:
    """One page's texts and status."""
    return _page_detail(_page_or_404(conn, book["id"], page_number))


@router.get("/books/{book_id}/pages/{page_number}/image")
def page_image(
    page_number: int,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """The scanned page image (only files inside the book's own pages folder are served)."""
    page = _page_or_404(conn, book["id"], page_number)
    if not page["image_path"]:
        raise HTTPException(status_code=404, detail="This page has no image yet.")
    try:
        pages_dir = safe_join(book_dir(settings.data_dir, book["uuid"]), "pages")
        path = safe_join(pages_dir, Path(page["image_path"]).name)
    except UnsafePathError as exc:
        raise HTTPException(status_code=404, detail="That image is not available.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The page image is missing.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.put("/books/{book_id}/pages/{page_number}/text", response_model=PageDetail)
def save_text(
    page_number: int,
    body: TextUpdate,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
) -> PageDetail:
    """Save the author's corrected text for a page."""
    review.save_corrected_text(conn, book["id"], page_number, body.text)
    return _page_detail(_page_or_404(conn, book["id"], page_number))


@router.post("/books/{book_id}/pages/approve")
def approve_many(
    body: ApproveRangeRequest, book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, int]:
    """Approve every read page in a range in one go (an explicit action by the author)."""
    approved, unread = review.approve_range(conn, book["id"], body.first_page, body.last_page)
    return {"approved": approved, "unread": unread}


@router.post("/books/{book_id}/pages/{page_number}/approve", response_model=PageDetail)
def approve(
    page_number: int, book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> PageDetail:
    """Approve the page's current text."""
    review.approve_page(conn, book["id"], page_number)
    return _page_detail(_page_or_404(conn, book["id"], page_number))


@router.post("/books/{book_id}/pages/{page_number}/restore", response_model=PageDetail)
def restore(
    page_number: int, book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> PageDetail:
    """Go back to the original OCR text for a page."""
    review.restore_original(conn, book["id"], page_number)
    return _page_detail(_page_or_404(conn, book["id"], page_number))


@router.get("/books/{book_id}/search", response_model=list[SearchHitOut])
def search(
    q: str, book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> list[SearchHitOut]:
    """Find pages containing the given words."""
    return [SearchHitOut(page_number=h.page_number, snippet=h.snippet) for h in review.search_text(conn, book["id"], q)]


@router.get("/books/{book_id}/lexicon")
def lexicon(book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, list]:
    """The Tamil words this book uses (with scores), for the Tanglish typing aid in the editor."""
    return {"words": [[word, score] for word, score in book_lexicon(conn, book["id"])]}


@router.get("/books/{book_id}/export")
def export_text(
    approved_only: bool = False, book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> PlainTextResponse:
    """Download the corrected text as a UTF-8 text file."""
    text = review.export_source_text(conn, book["id"], approved_only=approved_only)
    return PlainTextResponse(
        text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="book_{book["id"]}_corrected.txt"'},
    )
