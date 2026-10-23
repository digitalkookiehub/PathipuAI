"""Tell which writing system a text is in, to catch "translations" that came back in the wrong language."""

import unicodedata
from collections.abc import Iterable

from app.config import SUPPORTED_LANGUAGES

# Unicode blocks of the Indic scripts we support; English (and any Latin text) is counted as "en".
_BLOCKS = {
    "ta": (0x0B80, 0x0BFF),
    "te": (0x0C00, 0x0C7F),
    "kn": (0x0C80, 0x0CFF),
    "ml": (0x0D00, 0x0D7F),
    "hi": (0x0900, 0x097F),
}
MIN_LETTERS = 30  # shorter texts (headings, single words) are not judged
MAX_SOURCE_SHARE = 0.5  # more than this share in the book's own language means it was not translated
MIN_TARGET_SHARE = 0.3  # less than this share in the target language means the wrong language was used


def letter_counts(text: str) -> dict[str, int]:
    """How many letters (with their vowel signs) of the text belong to each supported language's script."""
    counts: dict[str, int] = {}
    for char in text:
        category = unicodedata.category(char)
        if not (category.startswith("L") or category.startswith("M")):
            continue
        code = ord(char)
        for language, (low, high) in _BLOCKS.items():
            if low <= code <= high:
                counts[language] = counts.get(language, 0) + 1
                break
        else:
            if category.startswith("L") and code < 0x250:  # Latin letters
                counts["en"] = counts.get("en", 0) + 1
    return counts


def untranslated_reason(
    text: str, source_language: str, target_language: str, ignore: Iterable[str] = ()
) -> str | None:
    """Why the text does not look like a translation into the target language, or None if it does.

    ignore lists terms that are meant to stay in the original script (glossary "keep unchanged" terms).
    """
    cleaned = text
    for term in ignore:
        if term:
            cleaned = cleaned.replace(term, " ")
    counts = letter_counts(cleaned)
    total = sum(counts.values())
    if total < MIN_LETTERS:
        return None
    source_name = SUPPORTED_LANGUAGES.get(source_language, (source_language,))[0]
    target_name = SUPPORTED_LANGUAGES.get(target_language, (target_language,))[0]
    if source_language != target_language and counts.get(source_language, 0) / total > MAX_SOURCE_SHARE:
        return f"This part is still mostly in {source_name}: it was not translated into {target_name}."
    if counts.get(target_language, 0) / total < MIN_TARGET_SHARE:
        return f"This part does not look like {target_name} text."
    return None
