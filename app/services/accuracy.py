"""Measure OCR accuracy from the author's own corrections (character error rate)."""

import re
import sqlite3
import unicodedata
from dataclasses import dataclass

from rapidfuzz.distance import Levenshtein

# Whitespace, digits, punctuation and invisible joiners are ignored so only reading mistakes count.
_IGNORED = re.compile(r"[\s\d\W_]|[\u200b-\u200d]")


def normalize(text: str) -> str:
    """Reduce text to its letters and marks."""
    return _IGNORED.sub("", unicodedata.normalize("NFC", text))


def cer(hypothesis: str, reference: str) -> float:
    """Character error rate of hypothesis against reference (0.0 is perfect)."""
    ref = normalize(reference)
    return Levenshtein.distance(normalize(hypothesis), ref) / max(len(ref), 1)


@dataclass(frozen=True)
class EngineAccuracy:
    """OCR accuracy of one engine on approved pages."""

    pages: int
    error_rate: float | None


@dataclass(frozen=True)
class AccuracyReport:
    """OCR accuracy measured on approved pages, overall and per OCR engine."""

    pages: int
    error_rate: float | None
    by_engine: dict[str, EngineAccuracy]


def book_ocr_accuracy(conn: sqlite3.Connection, book_id: int) -> AccuracyReport:
    """Compare original OCR text with the approved text on every approved page.

    An approved page without corrections counts as perfectly read.
    """
    totals: dict[str, list[int]] = {}  # engine -> [distance, length, pages]
    for row in conn.execute(
        "SELECT ocr_text, corrected_text, ocr_engine FROM book_pages "
        "WHERE book_id = ? AND ocr_status = 'done' AND review_status = 'approved'",
        (book_id,),
    ):
        reference = normalize(row["corrected_text"] if row["corrected_text"] is not None else row["ocr_text"] or "")
        entry = totals.setdefault(row["ocr_engine"] or "tesseract", [0, 0, 0])
        entry[0] += Levenshtein.distance(normalize(row["ocr_text"] or ""), reference)
        entry[1] += len(reference)
        entry[2] += 1
    distance = sum(e[0] for e in totals.values())
    length = sum(e[1] for e in totals.values())
    return AccuracyReport(
        pages=sum(e[2] for e in totals.values()),
        error_rate=distance / length if length else None,
        by_engine={
            name: EngineAccuracy(pages=e[2], error_rate=e[0] / e[1] if e[1] else None) for name, e in totals.items()
        },
    )
