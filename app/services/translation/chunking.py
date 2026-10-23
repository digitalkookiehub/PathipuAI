"""Split a chapter into ordered chunks that keep paragraph boundaries, so no request is huge."""

import hashlib
import re
import unicodedata

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


def paragraphs_of(page_texts: list[str]) -> list[str]:
    """Paragraphs in page order; a page without blank lines is one paragraph."""
    paragraphs: list[str] = []
    for text in page_texts:
        for paragraph in _PARAGRAPH_BREAK.split(text.strip()):
            cleaned = paragraph.strip()
            if cleaned:
                paragraphs.append(cleaned)
    return paragraphs


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    """Split one oversized paragraph at line ends, then sentence ends, then (last resort) at spaces."""
    pieces: list[str] = []
    current = ""
    units = [line for line in paragraph.split("\n") if line.strip()]
    expanded: list[str] = []
    for unit in units:
        expanded += _SENTENCE_END.split(unit) if len(unit) > max_chars else [unit]
    for unit in expanded:
        while len(unit) > max_chars:  # no sentence ends at all: cut at the last space before the limit
            cut = unit.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                pieces.append(current)
                current = ""
            pieces.append(unit[:cut].strip())
            unit = unit[cut:].strip()
        if current and len(current) + 1 + len(unit) > max_chars:
            pieces.append(current)
            current = unit
        else:
            current = f"{current}\n{unit}" if current else unit
    if current:
        pieces.append(current)
    return pieces


def split_into_chunks(page_texts: list[str], max_chars: int) -> list[str]:
    """Pack whole paragraphs into chunks of at most max_chars (a longer paragraph is split), in order."""
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs_of(page_texts):
        pieces = _split_long(paragraph, max_chars) if len(paragraph) > max_chars else [paragraph]
        for piece in pieces:
            if current and len(current) + 2 + len(piece) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def text_hash(text: str) -> str:
    """Fingerprint of a chunk's source text, used to notice when the approved source changed."""
    return hashlib.sha256(unicodedata.normalize("NFC", text).encode("utf-8")).hexdigest()
