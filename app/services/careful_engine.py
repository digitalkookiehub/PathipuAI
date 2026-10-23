"""Optional "careful reading" engine for Tamil and English: the ocr-tamil library.

It finds each word with a text detector and reads it with a Tamil recognition model. It is much more
accurate than Tesseract on difficult phone photos but slow on a CPU (about a minute per page). The library
returns words in a scrambled order, so the words are put back into reading order here using their positions.
"""

import importlib.util
import logging
import statistics
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from app.config import Settings

logger = logging.getLogger(__name__)

SUPPORTED_SOURCE_LANGUAGES = ("ta", "en")
SAME_LINE_FRACTION = 0.6  # words whose centres differ by less than this share of the word height are one line

_engine: Any = None
_lock = threading.Lock()  # the model is shared, so only one page is read at a time


@dataclass(frozen=True)
class Word:
    """A recognised word with its position on the page."""

    text: str
    left: float
    right: float
    center_y: float
    height: float
    confidence: float


def is_available() -> bool:
    """True when the ocr-tamil library is installed in this Python environment."""
    return importlib.util.find_spec("ocr_tamil") is not None


def group_words_into_lines(words: list[Word]) -> list[list[Word]]:
    """Arrange words into lines, top to bottom and left to right, following slightly tilted lines."""
    if not words:
        return []
    threshold = SAME_LINE_FRACTION * statistics.median(word.height for word in words)
    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda w: w.left):
        best: list[Word] | None = None
        for line in lines:
            last = line[-1]
            fits_after = word.left >= last.left + (last.right - last.left) * 0.5
            if fits_after and abs(word.center_y - last.center_y) < threshold:
                if best is None or abs(word.center_y - last.center_y) < abs(word.center_y - best[-1].center_y):
                    best = line
        if best is None:
            lines.append([word])
        else:
            best.append(word)
    lines.sort(key=lambda line: statistics.mean(word.center_y for word in line))
    return lines


def words_to_text(words: list[Word]) -> str:
    """The page text, one line per row, from positioned words."""
    return "\n".join(" ".join(word.text for word in line) for line in group_words_into_lines(words))


def _load_engine() -> Any:
    global _engine
    if _engine is None:
        logger.info("Loading the careful reading engine (first use can take a few minutes)")
        from ocr_tamil.ocr import OCR  # imported lazily: needs torch and downloads its models on first use

        _engine = OCR(detect=True, details=2, enable_cuda=True)
    return _engine


def _positioned_words(raw_result: list[Any]) -> list[Word]:
    words: list[Word] = []
    for text, confidence, (polygon, _line) in raw_result:
        if not str(text).strip():
            continue
        points = np.array(polygon)
        top, bottom = float(points[:, 1].min()), float(points[:, 1].max())
        words.append(
            Word(
                text=str(text).strip(),
                left=float(points[:, 0].min()),
                right=float(points[:, 0].max()),
                center_y=(top + bottom) / 2,
                height=max(bottom - top, 1.0),
                confidence=float(confidence),
            )
        )
    return words


def recognize(image: Image.Image, settings: Settings, language: str) -> tuple[str, float | None]:
    """Read a page image; returns the text and the mean word confidence (0-100)."""
    del settings, language  # the engine reads Tamil and English together
    engine = _load_engine()
    with _lock:
        raw = engine.predict(np.array(image.convert("L")))
    words = _positioned_words(raw[0] if raw else [])
    confidence = statistics.mean(w.confidence for w in words) * 100 if words else None
    return words_to_text(words), confidence
