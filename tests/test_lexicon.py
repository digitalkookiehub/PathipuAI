from fastapi.testclient import TestClient

from app.api.deps import get_settings
from app.api.main import create_app
from app.services import ocr, review
from app.services.books import create_book
from app.services.lexicon import book_lexicon


def make_book(conn, settings, make_pdf, texts):
    book = create_book(
        conn,
        settings,
        title="B",
        author="A",
        description="",
        source_language="ta",
        publication_details="",
        pdf_bytes=make_pdf(len(texts)),
    )
    it = iter(texts)
    ocr.process_book(conn, settings, book, recognizer=lambda i, s, lang: (next(it), 90.0), skip_setup_check=True)
    return book


def test_lexicon_trusts_reviewed_pages_more_than_raw_ocr(conn, settings, make_pdf):
    book = make_book(conn, settings, make_pdf, ["வணக்கம் நன்றி வணக்கம்", "வணக்கம் பாபா ஒன்று", "பாபா பாபா பாபா x y"])
    words = dict(book_lexicon(conn, book))
    assert words == {"வணக்கம்": 3, "பாபா": 4}  # raw OCR: counts of 1 each; words seen under 3 times are left out
    review.approve_page(conn, book, 1)  # a reviewed page counts three times
    words = dict(book_lexicon(conn, book))
    assert words["வணக்கம்"] == 7 and words["நன்றி"] == 3 and "ஒன்று" not in words
    assert list(words)[0] == "வணக்கம்"  # most used first


def test_corrected_text_replaces_ocr_text_and_non_tamil_is_ignored(conn, settings, make_pdf):
    book = make_book(conn, settings, make_pdf, ["தப்பு தப்பு தப்பு english 123"])
    review.save_corrected_text(conn, book, 1, "சரி சரி english 123 a")
    assert dict(book_lexicon(conn, book)) == {"சரி": 6}


def test_lexicon_endpoint(conn, settings, make_pdf):
    book = make_book(conn, settings, make_pdf, ["வணக்கம் வணக்கம் வணக்கம்"])
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    assert client.get(f"/api/books/{book}/lexicon").json() == {"words": [["வணக்கம்", 3]]}
    assert client.get("/api/books/999/lexicon").status_code == 404
