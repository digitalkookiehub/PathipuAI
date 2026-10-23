import pytest

from app.services import chapters, ocr, review
from app.services.books import create_book


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
        pdf_bytes=make_pdf(6),
    )
    ocr.process_book(conn, settings, book, recognizer=lambda i, s, lang: ("page text", 90.0), skip_setup_check=True)
    return book


def test_create_and_list_chapters_in_order(conn, book_id):
    first = chapters.create_chapter(conn, book_id, title="One", start_page=1, end_page=2)
    second = chapters.create_chapter(conn, book_id, title="Two", start_page=3, end_page=6, heading="Chapter Two")
    listed = chapters.list_chapters(conn, book_id)
    assert [c["id"] for c in listed] == [first, second]
    assert [c["order_index"] for c in listed] == [1, 2]
    assert listed[1]["page_count"] == 4 and listed[1]["heading"] == "Chapter Two"


def test_overlapping_and_invalid_ranges_rejected(conn, book_id):
    chapters.create_chapter(conn, book_id, title="One", start_page=2, end_page=4)
    with pytest.raises(chapters.ChapterError, match="already belong"):
        chapters.create_chapter(conn, book_id, title="Clash", start_page=4, end_page=5)
    with pytest.raises(chapters.ChapterError, match="between 1 and 6"):
        chapters.create_chapter(conn, book_id, title="Too far", start_page=5, end_page=9)
    with pytest.raises(chapters.ChapterError, match="not be after"):
        chapters.create_chapter(conn, book_id, title="Backwards", start_page=6, end_page=5)
    with pytest.raises(chapters.ChapterError, match="title"):
        chapters.create_chapter(conn, book_id, title="  ", start_page=5, end_page=5)


def test_update_chapter_may_keep_its_own_pages(conn, book_id):
    one = chapters.create_chapter(conn, book_id, title="One", start_page=1, end_page=3)
    chapters.update_chapter(conn, book_id, one, title="First", start_page=1, end_page=4, heading="H")
    row = chapters.get_chapter(conn, book_id, one)
    assert (row["title"], row["end_page"], row["heading"]) == ("First", 4, "H")
    chapters.create_chapter(conn, book_id, title="Two", start_page=5, end_page=6)
    with pytest.raises(chapters.ChapterError):
        chapters.update_chapter(conn, book_id, one, end_page=5)


def test_reorder_keeps_page_numbers(conn, book_id):
    one = chapters.create_chapter(conn, book_id, title="One", start_page=1, end_page=3)
    two = chapters.create_chapter(conn, book_id, title="Two", start_page=4, end_page=6)
    chapters.reorder_chapters(conn, book_id, [two, one])
    listed = chapters.list_chapters(conn, book_id)
    assert [c["id"] for c in listed] == [two, one]
    assert (listed[0]["start_page"], listed[1]["start_page"]) == (4, 1)  # original page numbers preserved
    with pytest.raises(chapters.ChapterError):
        chapters.reorder_chapters(conn, book_id, [one])


def test_delete_chapter_keeps_pages(conn, book_id):
    one = chapters.create_chapter(conn, book_id, title="One", start_page=1, end_page=3)
    chapters.delete_chapter(conn, book_id, one)
    assert chapters.list_chapters(conn, book_id) == []
    assert conn.execute("SELECT COUNT(*) FROM book_pages WHERE book_id = ?", (book_id,)).fetchone()[0] == 6
    with pytest.raises(chapters.ChapterError):
        chapters.get_chapter(conn, book_id, one)


def test_unassigned_ranges(conn, book_id):
    assert chapters.unassigned_ranges(conn, book_id) == [(1, 6)]
    chapters.create_chapter(conn, book_id, title="Mid", start_page=3, end_page=4)
    assert chapters.unassigned_ranges(conn, book_id) == [(1, 2), (5, 6)]
    chapters.create_chapter(conn, book_id, title="Rest", start_page=5, end_page=6)
    chapters.create_chapter(conn, book_id, title="Start", start_page=1, end_page=2)
    assert chapters.unassigned_ranges(conn, book_id) == []


def test_progress_counts_and_text(conn, book_id):
    one = chapters.create_chapter(conn, book_id, title="One", start_page=1, end_page=3, heading="The Beginning")
    review.save_corrected_text(conn, book_id, 2, "fixed page two")
    review.approve_page(conn, book_id, 2)
    row = chapters.get_chapter(conn, book_id, one)
    assert (row["read_pages"], row["approved_pages"], row["page_count"]) == (3, 1, 3)
    text = chapters.chapter_text(conn, book_id, one)
    assert text.startswith("The Beginning\n\n--- Page 1 ---\npage text")
    assert "--- Page 2 ---\nfixed page two" in text
    approved = chapters.chapter_text(conn, book_id, one, approved_only=True)
    assert "Page 2" in approved and "Page 1" not in approved
    assert [p.page_number for p in chapters.chapter_pages(conn, book_id, one)] == [1, 2, 3]


def test_chapters_cascade_when_book_deleted(conn, settings, book_id):
    from app.services.books import delete_book

    chapters.create_chapter(conn, book_id, title="One", start_page=1, end_page=3)
    delete_book(conn, settings, book_id)
    assert conn.execute("SELECT COUNT(*) FROM chapters").fetchone()[0] == 0
