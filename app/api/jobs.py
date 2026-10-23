"""Background OCR jobs so the web interface stays responsive during long runs."""

import logging
import threading
from dataclasses import dataclass

from app.config import Settings
from app.db import connect
from app.services.ocr import OcrSetupError, process_book

logger = logging.getLogger(__name__)


@dataclass
class _Job:
    thread: threading.Thread
    error: str | None = None


_jobs: dict[int, _Job] = {}
_last_errors: dict[int, str] = {}
_lock = threading.Lock()


def is_running(book_id: int) -> bool:
    """True while an OCR job for this book is in progress."""
    job = _jobs.get(book_id)
    return job is not None and job.thread.is_alive()


def last_error(book_id: int) -> str | None:
    """The friendly error from the most recent job that could not start or finish, if any."""
    return _last_errors.get(book_id)


def start_ocr(
    settings: Settings,
    book_id: int,
    *,
    first_page: int | None,
    last_page: int | None,
    retry_failed: bool,
    engine: str = "tesseract",
) -> None:
    """Start OCR in a background thread; raises OcrSetupError if one is already running."""
    with _lock:
        if is_running(book_id):
            raise OcrSetupError("This book is already being read. Please wait for it to finish.")
        _last_errors.pop(book_id, None)
        thread = threading.Thread(
            target=_run,
            args=(settings, book_id, first_page, last_page, retry_failed, engine),
            name=f"ocr-{book_id}",
            daemon=True,
        )
        _jobs[book_id] = _Job(thread=thread)
        thread.start()


def _run(
    settings: Settings, book_id: int, first_page: int | None, last_page: int | None, retry_failed: bool, engine: str
) -> None:
    conn = connect(settings.database_path)
    try:
        process_book(
            conn,
            settings,
            book_id,
            first_page=first_page,
            last_page=last_page,
            retry_failed=retry_failed,
            engine=engine,
        )
    except OcrSetupError as exc:
        _last_errors[book_id] = str(exc)
        logger.warning("OCR job for book=%s could not run: %s", book_id, exc)
    except Exception:
        _last_errors[book_id] = "Something went wrong while reading the pages. Please try again."
        logger.exception("OCR job crashed for book=%s", book_id)
    finally:
        conn.close()
