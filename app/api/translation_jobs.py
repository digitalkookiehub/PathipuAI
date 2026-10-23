"""Background translation jobs, so the web interface stays responsive while chapters are translated."""

import logging
import threading

from app.config import Settings
from app.db import connect
from app.services.translation import service as translation
from app.services.translation.base import TranslationProvider

logger = logging.getLogger(__name__)

_threads: dict[int, threading.Thread] = {}
_errors: dict[int, str] = {}
_lock = threading.Lock()


def is_running(book_id: int) -> bool:
    """True while a translation job for this book is in progress."""
    thread = _threads.get(book_id)
    return thread is not None and thread.is_alive()


def last_error(book_id: int) -> str | None:
    """The friendly error from the most recent job that stopped early, if any."""
    return _errors.get(book_id)


def start(settings: Settings, book_id: int, pairs: list[tuple[int, str]], provider: TranslationProvider) -> None:
    """Translate the prepared chapter/language pairs in a background thread (one job per book at a time)."""
    with _lock:
        if is_running(book_id):
            raise translation.TranslationError("This book is already being translated. Please wait for it to finish.")
        _errors.pop(book_id, None)
        thread = threading.Thread(
            target=_run, args=(settings, book_id, pairs, provider), name=f"translate-{book_id}", daemon=True
        )
        _threads[book_id] = thread
        thread.start()


def _run(settings: Settings, book_id: int, pairs: list[tuple[int, str]], provider: TranslationProvider) -> None:
    conn = connect(settings.database_path)
    try:
        summary = translation.run(conn, settings, book_id, pairs, provider)
        if summary.aborted:
            _errors[book_id] = summary.aborted
    except Exception:
        _errors[book_id] = "Something went wrong while translating. Please try again."
        logger.exception("Translation job crashed for book=%s", book_id)
    finally:
        conn.close()
