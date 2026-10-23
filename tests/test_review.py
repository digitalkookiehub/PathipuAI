import pytest

from app.services import ocr, review
from app.services.books import create_book, get_book


def fake_recognizer(image, settings, lang):
    return "original text", 90.0


@pytest.fixture
def book_id(conn, settings, make_pdf):
    book = create_book(
        conn,
        settings,
        title="B",
        author="A",
        description="",
        source_language="ta",
        publication_details="",
        pdf_bytes=make_pdf(3),
    )
    ocr.process_book(conn, settings, book, recognizer=fake_recognizer, skip_setup_check=True)
    return book


def page(conn, book_id, number=1):
    return review.get_page(conn, book_id, number)


def test_save_keeps_original_and_marks_corrected(conn, book_id):
    assert review.save_corrected_text(conn, book_id, 1, "fixed text") == "corrected"
    row = page(conn, book_id)
    assert row["ocr_text"] == "original text"
    assert row["corrected_text"] == "fixed text"
    assert review.current_text(row) == "fixed text"


def test_unchanged_save_changes_nothing(conn, book_id):
    assert review.save_corrected_text(conn, book_id, 1, "original text") == "pending"
    assert page(conn, book_id)["corrected_text"] is None


def test_approve_requires_explicit_action(conn, book_id):
    review.save_corrected_text(conn, book_id, 1, "fixed")
    assert page(conn, book_id)["review_status"] == "corrected"
    review.approve_page(conn, book_id, 1)
    row = page(conn, book_id)
    assert row["review_status"] == "approved" and row["approved_at"]


def test_editing_approved_text_requires_approval_again(conn, book_id):
    review.approve_page(conn, book_id, 1)
    review.save_corrected_text(conn, book_id, 1, "changed after approval")
    row = page(conn, book_id)
    assert row["review_status"] == "corrected"
    assert row["approved_at"] is None


def test_saving_same_text_keeps_approval(conn, book_id):
    review.save_corrected_text(conn, book_id, 1, "fixed")
    review.approve_page(conn, book_id, 1)
    review.save_corrected_text(conn, book_id, 1, "fixed")
    assert page(conn, book_id)["review_status"] == "approved"


def test_cannot_review_unread_page(conn, settings, make_pdf):
    book = create_book(
        conn,
        settings,
        title="C",
        author="A",
        description="",
        source_language="ta",
        publication_details="",
        pdf_bytes=make_pdf(1),
    )
    with pytest.raises(review.ReviewError):
        review.approve_page(conn, book, 1)
    with pytest.raises(review.ReviewError):
        review.save_corrected_text(conn, book, 1, "x")


def test_missing_page_rejected(conn, book_id):
    with pytest.raises(review.ReviewError):
        review.approve_page(conn, book_id, 99)


def test_restore_original(conn, book_id):
    review.save_corrected_text(conn, book_id, 1, "fixed")
    review.approve_page(conn, book_id, 1)
    review.restore_original(conn, book_id, 1)
    row = page(conn, book_id)
    assert row["corrected_text"] is None and row["review_status"] == "pending" and row["approved_at"] is None


def test_history_recorded(conn, book_id):
    review.save_corrected_text(conn, book_id, 1, "fixed")
    review.approve_page(conn, book_id, 1)
    actions = [r["action"] for r in conn.execute("SELECT action FROM text_history ORDER BY id")]
    assert actions == ["edit", "approve"]


def test_book_status_follows_review(conn, book_id):
    assert get_book(conn, book_id)["status"] == "needs_correction"
    review.approve_page(conn, book_id, 1)
    assert get_book(conn, book_id)["status"] == "awaiting_approval"
    for n in (2, 3):
        review.approve_page(conn, book_id, n)
    assert get_book(conn, book_id)["status"] == "approved"
    review.save_corrected_text(conn, book_id, 2, "edit")
    assert get_book(conn, book_id)["status"] == "awaiting_approval"


def test_review_counts(conn, book_id):
    review.save_corrected_text(conn, book_id, 1, "x")
    review.approve_page(conn, book_id, 2)
    assert review.review_counts(conn, book_id) == {"pending": 1, "corrected": 1, "approved": 1}


def test_search_uses_corrected_text_and_escapes(conn, book_id):
    review.save_corrected_text(conn, book_id, 2, "100% sure, வணக்கம்")
    assert [h.page_number for h in review.search_text(conn, book_id, "வணக்கம்")] == [2]
    assert [h.page_number for h in review.search_text(conn, book_id, "100%")] == [2]
    assert [h.page_number for h in review.search_text(conn, book_id, "original")] == [1, 3]
    assert review.search_text(conn, book_id, "   ") == []
    assert review.search_text(conn, book_id, "no such words") == []


def test_percent_alone_only_matches_literal(conn, book_id):
    assert review.search_text(conn, book_id, "%") == []
    assert review.search_text(conn, book_id, "_") == []


def test_export_text(conn, book_id):
    review.save_corrected_text(conn, book_id, 2, "page two fixed")
    review.approve_page(conn, book_id, 2)
    full = review.export_source_text(conn, book_id)
    assert "--- Page 1 ---\noriginal text" in full and "--- Page 2 ---\npage two fixed" in full
    approved = review.export_source_text(conn, book_id, approved_only=True)
    assert "Page 2" in approved and "Page 1" not in approved


def test_reread_protects_corrected_pages(conn, settings, book_id):
    review.save_corrected_text(conn, book_id, 1, "my work")
    with pytest.raises(ocr.OcrSetupError, match="Pages 1"):
        ocr.reset_pages_for_reread(conn, book_id, 1, 3)
    assert page(conn, book_id)["corrected_text"] == "my work"


def test_reread_replaces_ocr_text(conn, settings, book_id):
    assert ocr.reset_pages_for_reread(conn, book_id, 2, 3) == 2
    ocr.process_book(
        conn, settings, book_id, recognizer=lambda i, s, lang: ("new reading", 50.0), skip_setup_check=True
    )
    assert page(conn, book_id, 2)["ocr_text"] == "new reading"
    assert page(conn, book_id, 1)["ocr_text"] == "original text"


def test_reread_can_discard_corrections(conn, book_id):
    review.save_corrected_text(conn, book_id, 1, "my work")
    review.approve_page(conn, book_id, 1)
    ocr.reset_pages_for_reread(conn, book_id, 1, 1, discard_corrections=True)
    row = page(conn, book_id)
    assert row["corrected_text"] is None and row["review_status"] == "pending" and row["ocr_status"] == "not_started"


def test_accuracy_counts_only_approved_pages(conn, book_id):
    from app.services.accuracy import book_ocr_accuracy

    assert book_ocr_accuracy(conn, book_id).error_rate is None  # nothing approved yet
    review.approve_page(conn, book_id, 1)  # approved unchanged: read perfectly
    report = book_ocr_accuracy(conn, book_id)
    assert report.pages == 1 and report.error_rate == 0
    review.save_corrected_text(conn, book_id, 2, "original text with more words")
    review.approve_page(conn, book_id, 2)
    report = book_ocr_accuracy(conn, book_id)
    assert report.pages == 2 and 0 < report.error_rate < 1
    review.save_corrected_text(conn, book_id, 3, "unapproved edit entirely different")
    assert book_ocr_accuracy(conn, book_id).pages == 2  # unapproved pages are ignored


def test_approve_range_approves_read_pages_and_skips_the_rest(conn, settings, make_pdf):
    book = create_book(
        conn,
        settings,
        title="R",
        author="A",
        description="",
        source_language="ta",
        publication_details="",
        pdf_bytes=make_pdf(5),
    )
    ocr.process_book(
        conn, settings, book, recognizer=lambda i, s, lang: ("text", 90.0), skip_setup_check=True, last_page=3
    )
    review.save_corrected_text(conn, book, 2, "fixed")
    review.approve_page(conn, book, 1)  # already approved: not counted again
    assert review.approve_range(conn, book, 1, 5) == (2, 2)  # pages 2 and 3 approved; 4 and 5 are unread
    assert review.review_counts(conn, book)["approved"] == 3
    assert review.approve_range(conn, book, 1, 5) == (0, 2)  # nothing left to approve
    assert review.get_page(conn, book, 2)["corrected_text"] == "fixed"  # corrections are kept
    actions = [r["action"] for r in conn.execute("SELECT action FROM text_history ORDER BY id")]
    assert actions.count("approve") == 3
    assert get_book(conn, book)["status"] == "processing"  # reading is unfinished, so review does not change it


def test_approve_range_validates_the_range(conn, book_id):
    with pytest.raises(review.ReviewError, match="between 1 and 3"):
        review.approve_range(conn, book_id, 1, 9)
    with pytest.raises(review.ReviewError, match="not be after"):
        review.approve_range(conn, book_id, 3, 1)
    assert review.review_counts(conn, book_id)["approved"] == 0


def test_approve_range_completes_the_book(conn, book_id):
    assert review.approve_range(conn, book_id, 1, 3) == (3, 0)
    assert get_book(conn, book_id)["status"] == "approved"
