import pytest
from PIL import Image

from app.services import ocr
from app.services.books import create_book, get_book
from app.services.preprocessing import preprocess


def _book(conn, settings, make_pdf, pages=3):
    return create_book(
        conn,
        settings,
        title="B",
        author="A",
        description="",
        source_language="ta",
        publication_details="",
        pdf_bytes=make_pdf(pages),
    )


def fake_recognizer(image, settings, lang):
    return f"text {image.width}", 91.5


def page_rows(conn, book_id):
    return conn.execute(
        "SELECT page_number, ocr_status, ocr_text, error FROM book_pages WHERE book_id = ? ORDER BY page_number",
        (book_id,),
    ).fetchall()


def test_process_saves_text_and_images(conn, settings, make_pdf):
    book_id = _book(conn, settings, make_pdf)
    summary = ocr.process_book(conn, settings, book_id, recognizer=fake_recognizer, skip_setup_check=True)
    assert (summary.total, summary.completed, summary.failed) == (3, 3, 0)
    rows = page_rows(conn, book_id)
    assert all(r["ocr_status"] == "done" and r["ocr_text"].startswith("text") for r in rows)
    assert get_book(conn, book_id)["status"] == "needs_correction"
    saved = conn.execute("SELECT image_path FROM book_pages WHERE book_id = ?", (book_id,)).fetchall()
    assert all(Image.open(r["image_path"]).size[0] > 0 for r in saved)


def test_original_text_kept_and_corrected_untouched(conn, settings, make_pdf):
    book_id = _book(conn, settings, make_pdf, pages=1)
    ocr.process_book(conn, settings, book_id, recognizer=fake_recognizer, skip_setup_check=True)
    row = conn.execute("SELECT ocr_text, corrected_text FROM book_pages WHERE book_id = ?", (book_id,)).fetchone()
    assert row["ocr_text"] and row["corrected_text"] is None


def test_failed_page_does_not_stop_run_and_can_be_retried(conn, settings, make_pdf):
    book_id = _book(conn, settings, make_pdf)
    calls = {"n": 0}

    def flaky(image, settings, lang):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return "ok", 80.0

    summary = ocr.process_book(conn, settings, book_id, recognizer=flaky, skip_setup_check=True)
    assert (summary.completed, summary.failed) == (2, 1)
    assert [r["ocr_status"] for r in page_rows(conn, book_id)] == ["done", "failed", "done"]
    assert get_book(conn, book_id)["status"] == "failed"

    seen = []

    def counting(image, settings, lang):
        seen.append(1)
        return "fixed", 90.0

    summary = ocr.process_book(conn, settings, book_id, retry_failed=True, recognizer=counting, skip_setup_check=True)
    assert len(seen) == 1  # only the failed page was redone
    assert summary.completed == 1
    assert get_book(conn, book_id)["status"] == "needs_correction"


def test_resume_skips_finished_pages(conn, settings, make_pdf):
    book_id = _book(conn, settings, make_pdf)
    ocr.process_book(conn, settings, book_id, last_page=1, recognizer=fake_recognizer, skip_setup_check=True)
    seen = []

    def counting(image, settings, lang):
        seen.append(1)
        return "x", None

    summary = ocr.process_book(conn, settings, book_id, recognizer=counting, skip_setup_check=True)
    assert summary.total == 2 and len(seen) == 2


def test_interrupted_page_is_picked_up_again(conn, settings, make_pdf):
    book_id = _book(conn, settings, make_pdf, pages=2)
    conn.execute("UPDATE book_pages SET ocr_status = 'processing' WHERE book_id = ? AND page_number = 1", (book_id,))
    conn.commit()
    summary = ocr.process_book(conn, settings, book_id, recognizer=fake_recognizer, skip_setup_check=True)
    assert summary.completed == 2


def test_progress_callback(conn, settings, make_pdf):
    book_id = _book(conn, settings, make_pdf)
    events = []
    ocr.process_book(
        conn,
        settings,
        book_id,
        recognizer=fake_recognizer,
        skip_setup_check=True,
        progress=lambda done, total: events.append((done, total)),
    )
    assert events == [(1, 3), (2, 3), (3, 3)]


def test_missing_tesseract_gives_friendly_error(conn, settings, make_pdf, monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(ocr, "WINDOWS_TESSERACT_PATHS", ())
    book_id = _book(conn, settings, make_pdf, pages=1)
    with pytest.raises(ocr.OcrSetupError, match="not installed"):
        ocr.process_book(conn, settings, book_id)
    assert page_rows(conn, book_id)[0]["ocr_status"] == "not_started"


def test_missing_language_data_gives_friendly_error(settings, monkeypatch):
    monkeypatch.setattr(ocr, "installed_languages", lambda s: {"eng", "osd"})
    with pytest.raises(ocr.OcrSetupError, match="Tamil"):
        ocr.check_language(settings, "ta")
    assert ocr.check_language(settings, "en") == "eng"


def test_unsupported_language_rejected(settings):
    with pytest.raises(ocr.OcrSetupError):
        ocr.check_language(settings, "xx")


def test_preprocess_steps_return_grayscale_image():
    image = Image.new("RGB", (200, 100), "white")
    for steps in ((), ("contrast",), ("flatten",), ("denoise", "deskew", "threshold")):
        assert preprocess(image, steps).mode == "L"


def test_render_page_uses_dpi(tmp_path, make_pdf):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(make_pdf(1))
    low = ocr.render_page(pdf, 0, 72)
    high = ocr.render_page(pdf, 0, 144)
    assert abs(high.width - low.width * 2) <= 2


def test_tamil_zero_width_joiner_removed(settings, monkeypatch):
    data = {
        "text": ["பாபாவின்‌", "மொழிகள்‌"],
        "block_num": [1, 1],
        "par_num": [1, 1],
        "line_num": [1, 1],
        "conf": ["90", "80"],
    }
    monkeypatch.setattr(ocr, "configure_tesseract", lambda s: None)
    monkeypatch.setattr(ocr.pytesseract, "image_to_data", lambda *a, **k: data)
    text, confidence = ocr.tesseract_recognize(Image.new("L", (10, 10)), settings, "tam")
    assert text == "பாபாவின் மொழிகள்"
    assert confidence == 85
    text_en, _ = ocr.tesseract_recognize(Image.new("L", (10, 10)), settings, "eng")
    assert "‌" in text_en  # only the Tamil model's artifact is stripped


def test_stray_symbols_removed_but_real_text_kept(settings, monkeypatch):
    data = {
        "text": ["செய்வேன்.", "|", "!", "a|b", "வணக்கம்"],
        "block_num": [1, 1, 1, 1, 1],
        "par_num": [1, 1, 1, 1, 1],
        "line_num": [1, 1, 1, 2, 3],
        "conf": ["90", "10", "10", "90", "90"],
    }
    monkeypatch.setattr(ocr, "configure_tesseract", lambda s: None)
    monkeypatch.setattr(ocr.pytesseract, "image_to_data", lambda *a, **k: data)
    text, _ = ocr.tesseract_recognize(Image.new("L", (10, 10)), settings, "tam")
    assert text == "செய்வேன்.\na|b\nவணக்கம்"
