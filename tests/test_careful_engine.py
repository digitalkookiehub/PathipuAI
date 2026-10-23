import random
import time

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_settings
from app.api.main import create_app
from app.services import careful_engine, ocr, review
from app.services.accuracy import book_ocr_accuracy
from app.services.books import create_book
from app.services.careful_engine import Word


def word(text, left, y, width=100.0, height=40.0, confidence=0.99):
    return Word(text, left, left + width, y, height, confidence)


def test_words_are_put_back_in_reading_order():
    # Two lines, the second slightly tilted; words given in a scrambled order, as the library returns them.
    line_one = [word("ஒன்று", 50, 100), word("இரண்டு", 200, 102), word("மூன்று", 350, 98)]
    line_two = [word("நான்கு", 50, 300), word("ஐந்து", 200, 312), word("ஆறு", 350, 325)]
    scrambled = [line_two[2], line_one[1], line_two[0], line_one[2], line_one[0], line_two[1]]
    assert careful_engine.words_to_text(scrambled) == "ஒன்று இரண்டு மூன்று\nநான்கு ஐந்து ஆறு"


def test_ordering_is_stable_for_any_input_order():
    words = [word(f"w{row}{col}", 50 + col * 150, 100 + row * 120) for row in range(4) for col in range(3)]
    expected = careful_engine.words_to_text(words)
    for seed in range(5):
        shuffled = words[:]
        random.Random(seed).shuffle(shuffled)
        assert careful_engine.words_to_text(shuffled) == expected
    assert careful_engine.words_to_text([]) == ""


def test_check_engine_messages(settings, monkeypatch):
    monkeypatch.setattr(careful_engine, "is_available", lambda: False)
    with pytest.raises(ocr.OcrSetupError, match="not installed"):
        ocr.check_engine(settings, "ta", "careful")
    monkeypatch.setattr(careful_engine, "is_available", lambda: True)
    assert ocr.check_engine(settings, "ta", "careful") == ""
    with pytest.raises(ocr.OcrSetupError, match="Tamil and English"):
        ocr.check_engine(settings, "te", "careful")
    with pytest.raises(ocr.OcrSetupError, match="choose a reading method"):
        ocr.check_engine(settings, "ta", "magic")


def test_engine_status_reports_both_engines(settings, monkeypatch):
    monkeypatch.setattr(ocr, "check_language", lambda s, code: "tam")
    monkeypatch.setattr(careful_engine, "is_available", lambda: False)
    status = ocr.engine_status(settings, "ta")
    assert status["tesseract"]["ready"] is True
    assert status["careful"]["ready"] is False and "not installed" in status["careful"]["message"]


@pytest.fixture
def book_id(conn, settings, make_pdf):
    return create_book(
        conn,
        settings,
        title="B",
        author="A",
        description="",
        source_language="ta",
        publication_details="",
        pdf_bytes=make_pdf(3),
    )


def test_careful_engine_run_records_engine_and_uses_flattened_grayscale(conn, settings, book_id, monkeypatch):
    seen_modes = []

    def fake_recognize(image, settings, language):
        seen_modes.append(image.mode)
        return "careful text", 97.0

    monkeypatch.setattr(careful_engine, "is_available", lambda: True)
    monkeypatch.setattr(careful_engine, "recognize", fake_recognize)
    summary = ocr.process_book(conn, settings, book_id, engine="careful")
    assert summary.completed == 3 and seen_modes == ["L", "L", "L"]
    rows = conn.execute("SELECT ocr_engine, ocr_text FROM book_pages WHERE book_id = ?", (book_id,)).fetchall()
    assert {r["ocr_engine"] for r in rows} == {"careful"} and {r["ocr_text"] for r in rows} == {"careful text"}


def test_careful_run_refused_when_not_installed(conn, settings, book_id, monkeypatch):
    monkeypatch.setattr(careful_engine, "is_available", lambda: False)
    with pytest.raises(ocr.OcrSetupError, match="not installed"):
        ocr.process_book(conn, settings, book_id, engine="careful")
    assert conn.execute("SELECT COUNT(*) FROM book_pages WHERE ocr_status != 'not_started'").fetchone()[0] == 0


def test_default_engine_is_recorded_as_tesseract(conn, settings, book_id):
    ocr.process_book(
        conn, settings, book_id, recognizer=lambda i, s, lang: ("t", 80.0), skip_setup_check=True, last_page=1
    )
    assert conn.execute("SELECT ocr_engine FROM book_pages WHERE page_number = 1").fetchone()[0] == "tesseract"


def test_accuracy_is_reported_per_engine(conn, settings, book_id):
    ocr.process_book(
        conn, settings, book_id, recognizer=lambda i, s, lang: ("abcd efgh", 80.0), skip_setup_check=True, last_page=1
    )
    ocr.process_book(
        conn,
        settings,
        book_id,
        recognizer=lambda i, s, lang: ("abcd efgh", 95.0),
        skip_setup_check=True,
        first_page=2,
        engine="careful",
    )
    conn.execute("UPDATE book_pages SET ocr_text = 'abcdefgh' WHERE page_number IN (1, 2)")
    conn.commit()
    review.save_corrected_text(conn, book_id, 1, "abcdxxxx")  # fast engine: 4 of 8 letters wrong
    review.approve_page(conn, book_id, 1)
    review.approve_page(conn, book_id, 2)  # careful engine: approved unchanged
    report = book_ocr_accuracy(conn, book_id)
    assert report.pages == 2
    assert report.by_engine["tesseract"].error_rate == 0.5
    assert report.by_engine["careful"].error_rate == 0.0
    assert report.error_rate == 0.25


@pytest.fixture
def client(settings, monkeypatch):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(ocr, "check_language", lambda s, code: "tam")
    monkeypatch.setattr(ocr, "tesseract_recognize", lambda image, s, lang: ("fast", 70.0))
    return TestClient(app)


def upload(client, make_pdf):
    response = client.post(
        "/api/books",
        data={"title": "B", "author": "A", "source_language": "ta"},
        files={"file": ("a.pdf", make_pdf(2), "application/pdf")},
    )
    return response.json()["id"]


def wait(client, book_id):
    for _ in range(300):
        if not client.get(f"/api/books/{book_id}/ocr").json()["running"]:
            return
        time.sleep(0.1)
    raise AssertionError("OCR did not finish")


def test_api_refuses_careful_engine_when_not_installed(client, make_pdf, monkeypatch):
    monkeypatch.setattr(careful_engine, "is_available", lambda: False)
    book_id = upload(client, make_pdf)
    status = client.get(f"/api/books/{book_id}/ocr").json()
    assert status["engines"]["tesseract"]["ready"] is True and status["engines"]["careful"]["ready"] is False
    refused = client.post(f"/api/books/{book_id}/ocr", json={"engine": "careful"})
    assert refused.status_code == 400 and "not installed" in refused.json()["detail"]
    assert client.post(f"/api/books/{book_id}/ocr", json={"engine": "bogus"}).status_code == 422


def test_api_runs_careful_engine_and_reports_it(client, make_pdf, monkeypatch):
    monkeypatch.setattr(careful_engine, "is_available", lambda: True)
    monkeypatch.setattr(careful_engine, "recognize", lambda image, s, lang: ("slow but exact", 99.0))
    book_id = upload(client, make_pdf)
    assert client.post(f"/api/books/{book_id}/ocr", json={"engine": "careful", "last_page": 1}).status_code == 202
    wait(client, book_id)
    page = client.get(f"/api/books/{book_id}/pages/1").json()
    assert page["ocr_engine"] == "careful" and page["text"] == "slow but exact"
    client.post(f"/api/books/{book_id}/ocr", json={"first_page": 2})  # default engine
    wait(client, book_id)
    assert client.get(f"/api/books/{book_id}/pages/2").json()["ocr_engine"] == "tesseract"
    client.post(f"/api/books/{book_id}/pages/1/approve")
    accuracy = client.get(f"/api/books/{book_id}/ocr").json()["accuracy"]
    assert accuracy["by_engine"]["careful"] == {"pages": 1, "error_rate": 0.0}
