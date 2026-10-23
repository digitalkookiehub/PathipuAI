"""Page-by-page local OCR (Tesseract, or the optional careful engine). Results are saved after every page."""

import logging
import os
import re
import shutil
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pytesseract
from PIL import Image

from app.config import SUPPORTED_LANGUAGES, Settings
from app.services import careful_engine
from app.services.pdf_validation import has_enough_disk
from app.services.preprocessing import preprocess
from app.storage import book_dir

logger = logging.getLogger(__name__)

WINDOWS_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)
ESTIMATED_MB_PER_PAGE = 2
ZERO_WIDTH_NON_JOINER = chr(0x200C)
_STRAY_SYMBOLS = re.compile(r"(?<!\S)[|!\\_~]+(?!\S)")  # lone marks Tesseract invents from page edges
PAGE_IMAGE_QUALITY = 85
ENGINE_TESSERACT = "tesseract"
ENGINE_CAREFUL = "careful"
ENGINES = (ENGINE_TESSERACT, ENGINE_CAREFUL)

Recognizer = Callable[[Image.Image, Settings, str], tuple[str, float | None]]
ProgressCallback = Callable[[int, int], None]


class OcrSetupError(Exception):
    """OCR cannot run because of installation or configuration; message is user-friendly."""


@dataclass(frozen=True)
class OcrRunSummary:
    """Result of one OCR run."""

    total: int
    completed: int
    failed: int


def resolve_tesseract_cmd(settings: Settings) -> str:
    """Find the Tesseract executable, checking PATH and common Windows locations."""
    found = shutil.which(settings.tesseract_cmd)
    if found:
        return found
    for candidate in WINDOWS_TESSERACT_PATHS:
        if Path(candidate).is_file():
            return candidate
    raise OcrSetupError(
        "Tesseract OCR is not installed on this computer, so pages cannot be read yet. "
        "Please install Tesseract (see the README) or set TESSERACT_CMD."
    )


def _tess_config(settings: Settings) -> str:
    return f"--psm {settings.ocr_psm} {settings.ocr_extra_config}".strip()


def configure_tesseract(settings: Settings) -> None:
    """Point pytesseract at the executable and, if configured, the language data folder."""
    pytesseract.pytesseract.tesseract_cmd = resolve_tesseract_cmd(settings)
    if settings.tessdata_dir:
        os.environ["TESSDATA_PREFIX"] = str(settings.tessdata_dir)


def installed_languages(settings: Settings) -> set[str]:
    """Return the Tesseract language codes available for OCR."""
    configure_tesseract(settings)
    try:
        return set(pytesseract.get_languages())
    except pytesseract.TesseractError as exc:
        logger.warning("Could not list Tesseract languages")
        raise OcrSetupError("Tesseract is installed but its language data could not be read.") from exc


def check_language(settings: Settings, language_code: str) -> str:
    """Verify OCR data for the language exists; return the Tesseract code."""
    if language_code not in SUPPORTED_LANGUAGES:
        raise OcrSetupError("This language is not supported yet.")
    name, tess_code = SUPPORTED_LANGUAGES[language_code]
    if tess_code not in installed_languages(settings):
        raise OcrSetupError(
            f"The {name} reading data ('{tess_code}') is not installed for Tesseract. "
            f"Please install it (see the README) before reading {name} pages."
        )
    return tess_code


def check_engine(settings: Settings, language_code: str, engine: str) -> str:
    """Verify the chosen engine can read this language; returns the Tesseract language code ('' if unused)."""
    if engine == ENGINE_TESSERACT:
        return check_language(settings, language_code)
    if engine != ENGINE_CAREFUL:
        raise OcrSetupError("Please choose a reading method from the list.")
    if language_code not in careful_engine.SUPPORTED_SOURCE_LANGUAGES:
        raise OcrSetupError("The careful reading method works for Tamil and English books only.")
    if not careful_engine.is_available():
        raise OcrSetupError(
            "The careful reading method is not installed on this computer. "
            "Install it with: pip install -r requirements-ocr-tamil.txt (see the README)."
        )
    return ""


def engine_status(settings: Settings, language_code: str) -> dict[str, dict[str, object]]:
    """For each engine: whether it can read this book's language right now, and why not."""
    status: dict[str, dict[str, object]] = {}
    for engine in ENGINES:
        try:
            check_engine(settings, language_code, engine)
            status[engine] = {"ready": True, "message": None}
        except OcrSetupError as exc:
            status[engine] = {"ready": False, "message": str(exc)}
    return status


def render_page(pdf_path: Path, page_index: int, dpi: int) -> Image.Image:
    """Render a single PDF page to a PIL image; only that page is held in memory."""
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        page = pdf[page_index]
        try:
            bitmap = page.render(scale=dpi / 72)
            return bitmap.to_pil().convert("RGB")
        finally:
            page.close()
    finally:
        pdf.close()


def tesseract_recognize(image: Image.Image, settings: Settings, tess_lang: str) -> tuple[str, float | None]:
    """Run Tesseract; return text (lines and paragraphs kept) and mean word confidence (0-100)."""
    configure_tesseract(settings)
    data = pytesseract.image_to_data(
        image, lang=tess_lang, config=_tess_config(settings), output_type=pytesseract.Output.DICT
    )
    lines: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []
    for i, word in enumerate(data["text"]):
        if not word.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
        conf = float(data["conf"][i])
        if conf >= 0:
            confidences.append(conf)
    paragraphs: dict[tuple[int, int], list[str]] = {}
    for (block, par, _line), words in lines.items():
        paragraphs.setdefault((block, par), []).append(" ".join(words))
    text = "\n\n".join("\n".join(par_lines) for par_lines in paragraphs.values())
    text = "\n".join(_STRAY_SYMBOLS.sub("", line).strip() for line in text.split("\n"))
    if tess_lang == "tam":
        # The Tamil model inserts an invisible joiner after the pulli; it breaks search and translation.
        text = text.replace(ZERO_WIDTH_NON_JOINER, "")
    confidence = sum(confidences) / len(confidences) if confidences else None
    return text, confidence


def ocr_page(
    pdf_path: Path,
    page_index: int,
    settings: Settings,
    tess_lang: str,
    recognizer: Recognizer | None = None,
    steps: tuple[str, ...] | None = None,
) -> tuple[Image.Image, str, float | None]:
    """Render and OCR one page. Returns (original image, text, confidence)."""
    recognizer = recognizer or tesseract_recognize
    image = render_page(pdf_path, page_index, settings.ocr_dpi)
    prepared = preprocess(image, settings.ocr_preprocess if steps is None else steps)
    text, confidence = recognizer(prepared, settings, tess_lang)
    return image, text, confidence


def _save_page_image(image: Image.Image, pages_dir: Path, page_number: int) -> Path:
    path = pages_dir / f"{page_number:04d}.jpg"
    image.convert("L").save(path, "JPEG", quality=PAGE_IMAGE_QUALITY)
    return path


def process_book(
    conn: sqlite3.Connection,
    settings: Settings,
    book_id: int,
    *,
    first_page: int | None = None,
    last_page: int | None = None,
    retry_failed: bool = False,
    progress: ProgressCallback | None = None,
    recognizer: Recognizer | None = None,
    skip_setup_check: bool = False,
    engine: str = ENGINE_TESSERACT,
) -> OcrRunSummary:
    """OCR pages that are not done yet (and failed ones when retry_failed), one at a time.

    Finished pages are never redone, so an interrupted run simply resumes. A failing page is
    recorded and the run continues with the next page.
    """
    careful = engine == ENGINE_CAREFUL
    recognizer = recognizer or (careful_engine.recognize if careful else tesseract_recognize)
    steps = settings.careful_preprocess if careful else settings.ocr_preprocess
    book = conn.execute(
        "SELECT id, uuid, source_language, original_pdf_path FROM books WHERE id = ?", (book_id,)
    ).fetchone()
    if book is None:
        raise OcrSetupError("That book no longer exists.")
    tess_lang = "" if skip_setup_check else check_engine(settings, book["source_language"], engine)

    wanted = ("not_started", "processing", "failed") if retry_failed else ("not_started", "processing")
    query = "SELECT id, page_number FROM book_pages WHERE book_id = ? AND ocr_status IN ({})".format(
        ",".join("?" * len(wanted))
    )
    params: list[object] = [book_id, *wanted]
    if first_page is not None:
        query += " AND page_number >= ?"
        params.append(first_page)
    if last_page is not None:
        query += " AND page_number <= ?"
        params.append(last_page)
    pending = conn.execute(query + " ORDER BY page_number", params).fetchall()

    root = book_dir(settings.data_dir, book["uuid"])
    if pending and not has_enough_disk(root, settings.min_free_disk_mb + ESTIMATED_MB_PER_PAGE * len(pending)):
        raise OcrSetupError("There is not enough free disk space on the server to read these pages.")

    pdf_path = Path(book["original_pdf_path"])
    pages_dir = root / "pages"
    pages_dir.mkdir(exist_ok=True)

    with conn:
        conn.execute(
            "UPDATE processing_jobs SET status = 'interrupted', updated_at = datetime('now') "
            "WHERE book_id = ? AND job_type = 'ocr' AND status = 'processing'",
            (book_id,),
        )
        job_id = conn.execute(
            "INSERT INTO processing_jobs (book_id, job_type, status, total, started_at) "
            "VALUES (?, 'ocr', 'processing', ?, datetime('now'))",
            (book_id, len(pending)),
        ).lastrowid
        conn.execute("UPDATE books SET status = 'processing', updated_at = datetime('now') WHERE id = ?", (book_id,))

    completed = failed = 0
    for done, row in enumerate(pending, start=1):
        page_number = row["page_number"]
        with conn:
            conn.execute(
                "UPDATE book_pages SET ocr_status = 'processing', updated_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
        started = time.monotonic()
        try:
            image, text, confidence = ocr_page(pdf_path, page_number - 1, settings, tess_lang, recognizer, steps)
            image_path = _save_page_image(image, pages_dir, page_number)
            del image
            duration_ms = int((time.monotonic() - started) * 1000)
            with conn:
                conn.execute(
                    "UPDATE book_pages SET ocr_status = 'done', ocr_text = ?, ocr_confidence = ?, "
                    "image_path = ?, duration_ms = ?, ocr_engine = ?, error = NULL, updated_at = datetime('now') "
                    "WHERE id = ?",
                    (text, confidence, str(image_path), duration_ms, engine, row["id"]),
                )
            completed += 1
        except Exception as exc:  # one bad page must not stop the whole book
            logger.exception("OCR failed for book=%s page=%s", book_id, page_number)
            with conn:
                conn.execute(
                    "UPDATE book_pages SET ocr_status = 'failed', error = ?, duration_ms = ?, "
                    "updated_at = datetime('now') WHERE id = ?",
                    (type(exc).__name__, int((time.monotonic() - started) * 1000), row["id"]),
                )
            failed += 1
        with conn:
            conn.execute(
                "UPDATE processing_jobs SET completed = ?, failed = ?, updated_at = datetime('now') WHERE id = ?",
                (completed, failed, job_id),
            )
        if progress:
            progress(done, len(pending))

    _finish(conn, book_id, job_id, failed)
    return OcrRunSummary(total=len(pending), completed=completed, failed=failed)


def _finish(conn: sqlite3.Connection, book_id: int, job_id: int, failed_this_run: int) -> None:
    counts = page_status_counts(conn, book_id)
    if counts.get("failed"):
        status = "failed"
    elif counts.get("not_started") or counts.get("processing"):
        status = "processing"
    else:
        status = "needs_correction"
    with conn:
        conn.execute(
            "UPDATE processing_jobs SET status = ?, finished_at = datetime('now'), updated_at = datetime('now') "
            "WHERE id = ?",
            ("failed" if failed_this_run else "done", job_id),
        )
        conn.execute("UPDATE books SET status = ?, updated_at = datetime('now') WHERE id = ?", (status, book_id))


def reset_pages_for_reread(
    conn: sqlite3.Connection,
    book_id: int,
    first_page: int,
    last_page: int,
    *,
    discard_corrections: bool = False,
) -> int:
    """Mark pages as not read so they can be OCR'd again; return how many pages were reset.

    Pages the author has corrected or approved are protected unless discard_corrections is True.
    """
    protected = conn.execute(
        "SELECT page_number FROM book_pages WHERE book_id = ? AND page_number BETWEEN ? AND ? "
        "AND (corrected_text IS NOT NULL OR review_status != 'pending') ORDER BY page_number",
        (book_id, first_page, last_page),
    ).fetchall()
    if protected and not discard_corrections:
        pages = ", ".join(str(r["page_number"]) for r in protected)
        raise OcrSetupError(
            f"Pages {pages} already have corrections or approval. "
            "Tick 'Discard my corrections' if you really want to read them again."
        )
    with conn:
        cur = conn.execute(
            "UPDATE book_pages SET ocr_status = 'not_started', ocr_text = NULL, ocr_confidence = NULL, "
            "ocr_engine = NULL, error = NULL, corrected_text = NULL, review_status = 'pending', approved_at = NULL, "
            "updated_at = datetime('now') WHERE book_id = ? AND page_number BETWEEN ? AND ?",
            (book_id, first_page, last_page),
        )
    return cur.rowcount


def page_status_counts(conn: sqlite3.Connection, book_id: int) -> dict[str, int]:
    """Return how many pages are in each OCR status."""
    return {
        row["ocr_status"]: row["n"]
        for row in conn.execute(
            "SELECT ocr_status, COUNT(*) AS n FROM book_pages WHERE book_id = ? GROUP BY ocr_status",
            (book_id,),
        )
    }
