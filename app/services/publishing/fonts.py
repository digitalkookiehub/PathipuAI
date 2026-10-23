"""Bundled Unicode fonts for publishing, and a check that they can draw every character of the text."""

import functools
import unicodedata
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont

FONT_DIR = Path(__file__).resolve().parents[2] / "fonts"
LATIN = "NotoSans"
FAMILIES = {
    "ta": "NotoSansTamil",
    "te": "NotoSansTelugu",
    "kn": "NotoSansKannada",
    "ml": "NotoSansMalayalam",
    "hi": "NotoSansDevanagari",
    "en": LATIN,
}
# Joiners shape letters but have no glyph of their own.
_INVISIBLE = {0x00AD, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF}


def font_path(family: str, bold: bool = False) -> Path:
    """Path of a bundled font file."""
    return FONT_DIR / f"{family}-{'Bold' if bold else 'Regular'}.ttf"


def family_for(language: str) -> str:
    """The font family that draws a language's script."""
    return FAMILIES.get(language, LATIN)


def register_fonts(pdf: Any) -> None:
    """Add every bundled font (regular and bold) to an FPDF document."""
    for family in dict.fromkeys(FAMILIES.values()):
        pdf.add_font(family, "", str(font_path(family)))
        pdf.add_font(family, "B", str(font_path(family, bold=True)))


@functools.lru_cache(maxsize=None)
def _characters(family: str, bold: bool = False) -> frozenset[int]:
    font = TTFont(font_path(family, bold), lazy=True)
    try:
        return frozenset(font.getBestCmap())
    finally:
        font.close()


def fallback_families(source_language: str | None) -> list[str]:
    """Fonts tried, in order, for characters the main font lacks: Latin, then the book's own script.

    The book's own script matters because glossary terms marked "keep unchanged" stay in the original script
    even inside a translation.
    """
    return list(dict.fromkeys([LATIN, family_for(source_language)])) if source_language else [LATIN]


def missing_glyphs(text: str, language: str, source_language: str | None = None) -> set[str]:
    """Characters of the text that neither the language's font nor the fallback fonts can draw."""
    covers = [
        _characters(family) for family in dict.fromkeys([family_for(language), *fallback_families(source_language)])
    ]
    missing: set[str] = set()
    for char in text:
        code = ord(char)
        if char.isspace() or code in _INVISIBLE or unicodedata.category(char) in ("Cc", "Cf"):
            continue
        if not any(code in cover for cover in covers):
            missing.add(char)
    return missing
