"""A list of the Tamil words used in a book, for the typing aid that turns English letters into Tamil.

Typing Tamil with English letters ("Tanglish") is ambiguous: "vanakkam" could be வனக்கம் or வணக்கம். Knowing which
words the book really uses lets the browser pick the right spelling. Words from pages the author corrected or
approved count more than raw OCR text, which can contain mistakes.
"""

import re
import sqlite3
from collections import Counter

_TAMIL_WORD = re.compile(r"[஀-௿]{2,}")
REVIEWED_WEIGHT = 3  # a word seen once on a reviewed page is trusted; a single OCR sighting is not
MIN_SCORE = 3
MAX_WORDS = 8000


def book_lexicon(conn: sqlite3.Connection, book_id: int) -> list[tuple[str, int]]:
    """The book's Tamil words with a usage score, most used first."""
    scores: Counter[str] = Counter()
    rows = conn.execute(
        "SELECT COALESCE(corrected_text, ocr_text, '') AS text, review_status FROM book_pages "
        "WHERE book_id = ? AND ocr_status = 'done'",
        (book_id,),
    )
    for row in rows:
        weight = REVIEWED_WEIGHT if row["review_status"] in ("corrected", "approved") else 1
        for word in _TAMIL_WORD.findall(row["text"]):
            scores[word] += weight
    return [(word, score) for word, score in scores.most_common(MAX_WORDS) if score >= MIN_SCORE]
