from app.services.pdf_validation import count_pages, validate_pdf


def test_count_pages(make_pdf):
    assert count_pages(make_pdf(3)) == 3


def test_valid_pdf(make_pdf):
    result = validate_pdf(make_pdf(4), max_upload_mb=5, max_pages=10)
    assert result.ok
    assert result.page_count == 4


def test_empty_file_rejected():
    assert not validate_pdf(b"", 5, 10).ok


def test_non_pdf_rejected():
    result = validate_pdf(b"hello world", 5, 10)
    assert not result.ok
    assert "PDF" in result.message


def test_corrupt_pdf_rejected():
    result = validate_pdf(b"%PDF-1.4 garbage", 5, 10)
    assert not result.ok


def test_too_many_pages_rejected(make_pdf):
    result = validate_pdf(make_pdf(3), max_upload_mb=5, max_pages=2)
    assert not result.ok
    assert "limit" in result.message


def test_too_large_rejected(make_pdf):
    result = validate_pdf(make_pdf(1), max_upload_mb=0, max_pages=10)
    assert not result.ok
