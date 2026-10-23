from pathlib import Path

import pytest

from app.db import migrate
from app.services.books import BookError, create_book, delete_book, get_book, list_books


def _create(conn, settings, pdf, **overrides):
    args = {
        "title": "Test Book",
        "author": "Guru",
        "description": "",
        "source_language": "ta",
        "publication_details": "",
        "pdf_bytes": pdf,
    }
    args.update(overrides)
    return create_book(conn, settings, **args)


def test_migrations_idempotent(conn):
    assert migrate(conn) == []


def test_create_and_get_book(conn, settings, make_pdf):
    book_id = _create(conn, settings, make_pdf(3))
    book = get_book(conn, book_id)
    assert book["page_count"] == 3
    assert Path(book["original_pdf_path"]).is_file()
    pages = conn.execute("SELECT COUNT(*) FROM book_pages WHERE book_id = ?", (book_id,)).fetchone()[0]
    assert pages == 3
    assert [b["id"] for b in list_books(conn)] == [book_id]


def test_duplicate_book_not_overwritten(conn, settings, make_pdf):
    _create(conn, settings, make_pdf(1))
    with pytest.raises(BookError):
        _create(conn, settings, make_pdf(2), title="test book")
    assert len(list_books(conn)) == 1


def test_invalid_pdf_creates_nothing(conn, settings):
    with pytest.raises(BookError):
        _create(conn, settings, b"not a pdf")
    assert list_books(conn) == []
    assert not (settings.data_dir / "books").exists() or not any((settings.data_dir / "books").iterdir())


def test_requires_title_and_supported_language(conn, settings, make_pdf):
    with pytest.raises(BookError):
        _create(conn, settings, make_pdf(1), title="  ")
    with pytest.raises(BookError):
        _create(conn, settings, make_pdf(1), source_language="xx")


def test_delete_book_removes_files_and_rows(conn, settings, make_pdf):
    book_id = _create(conn, settings, make_pdf(2))
    pdf_path = Path(get_book(conn, book_id)["original_pdf_path"])
    delete_book(conn, settings, book_id)
    assert get_book(conn, book_id) is None
    assert not pdf_path.parent.exists()
    assert conn.execute("SELECT COUNT(*) FROM book_pages").fetchone()[0] == 0


def test_connection_usable_from_another_thread(conn):
    import threading

    errors: list[Exception] = []

    def use() -> None:
        try:
            conn.execute("SELECT COUNT(*) FROM books").fetchone()
        except Exception as exc:  # noqa: BLE001 - recorded and asserted below
            errors.append(exc)

    thread = threading.Thread(target=use)
    thread.start()
    thread.join()
    assert errors == []
