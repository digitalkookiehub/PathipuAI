"""Validate uploaded PDFs before anything is stored or processed."""

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating an uploaded PDF."""

    ok: bool
    page_count: int = 0
    message: str = ""


def count_pages(data: bytes) -> int:
    """Return the number of pages in the PDF bytes. Raises ValueError if unreadable."""
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ValueError("The PDF could not be opened.") from exc
    try:
        return len(pdf)
    finally:
        pdf.close()


def validate_pdf(data: bytes, max_upload_mb: int, max_pages: int) -> ValidationResult:
    """Check type, size, readability and page count; return a friendly result."""
    if not data:
        return ValidationResult(False, message="The file is empty. Please choose your scanned PDF.")
    if len(data) > max_upload_mb * 1024 * 1024:
        return ValidationResult(
            False, message=f"The file is larger than the {max_upload_mb} MB limit. Try a smaller scan."
        )
    if not data.startswith(PDF_MAGIC):
        return ValidationResult(False, message="This does not look like a PDF file.")
    try:
        pages = count_pages(data)
    except ValueError:
        logger.warning("Uploaded PDF could not be read")
        return ValidationResult(False, message="This PDF is damaged or protected and cannot be read.")
    if pages < 1:
        return ValidationResult(False, message="This PDF has no pages.")
    if pages > max_pages:
        return ValidationResult(False, message=f"This PDF has {pages} pages; the limit is {max_pages}.")
    return ValidationResult(True, page_count=pages)


def has_enough_disk(path: Path, required_mb: int) -> bool:
    """True when the filesystem holding path has at least required_mb free."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free >= required_mb * 1024 * 1024
