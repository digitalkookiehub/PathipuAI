"""Glossary of the book's special terms (mantras, sacred names, Sanskrit words, ...).

Each term has one term-level row (language_code '*') holding the explanation, the author's notes and the
keep-unchanged flag, plus optional rows with the preferred translation for individual languages.
"""

import sqlite3
import unicodedata
from dataclasses import dataclass, field

from app.config import SUPPORTED_LANGUAGES
from app.services.books import BookError

ALL_LANGUAGES = "*"


class GlossaryError(BookError):
    """A glossary problem the author can fix; the message is safe to show them."""


@dataclass
class GlossaryTerm:
    """One glossary term with its per-language translations."""

    id: int
    source_term: str
    explanation: str
    author_notes: str
    keep_unchanged: bool
    translations: dict[str, str] = field(default_factory=dict)


def _clean_term(term: str) -> str:
    cleaned = unicodedata.normalize("NFC", term).strip()
    if not cleaned:
        raise GlossaryError("Please enter the term.")
    return cleaned


def _clean_translations(conn: sqlite3.Connection, book_id: int, translations: dict[str, str]) -> dict[str, str]:
    source = conn.execute("SELECT source_language FROM books WHERE id = ?", (book_id,)).fetchone()
    if source is None:
        raise GlossaryError("That book no longer exists.")
    cleaned: dict[str, str] = {}
    for code, value in translations.items():
        if code not in SUPPORTED_LANGUAGES:
            raise GlossaryError("One of the languages is not supported.")
        if code == source["source_language"]:
            raise GlossaryError("A term cannot be translated into the book's own language.")
        if value.strip():
            cleaned[code] = unicodedata.normalize("NFC", value).strip()
    return cleaned


def list_terms(conn: sqlite3.Connection, book_id: int) -> list[GlossaryTerm]:
    """All terms of the book, sorted by term."""
    terms: dict[str, GlossaryTerm] = {}
    rows = conn.execute(
        "SELECT id, source_term, language_code, preferred_translation, explanation, keep_unchanged, author_notes "
        "FROM glossary_terms WHERE book_id = ? ORDER BY source_term, language_code",
        (book_id,),
    ).fetchall()
    for row in rows:
        if row["language_code"] == ALL_LANGUAGES:
            terms[row["source_term"]] = GlossaryTerm(
                row["id"], row["source_term"], row["explanation"], row["author_notes"], bool(row["keep_unchanged"])
            )
    for row in rows:
        if row["language_code"] != ALL_LANGUAGES and row["source_term"] in terms:
            terms[row["source_term"]].translations[row["language_code"]] = row["preferred_translation"]
    return list(terms.values())


def get_term(conn: sqlite3.Connection, book_id: int, term_id: int) -> GlossaryTerm:
    """One term of the book or GlossaryError."""
    for term in list_terms(conn, book_id):
        if term.id == term_id:
            return term
    raise GlossaryError("That glossary term was not found.")


def _write_translations(conn: sqlite3.Connection, book_id: int, term: str, translations: dict[str, str]) -> None:
    conn.execute(
        "DELETE FROM glossary_terms WHERE book_id = ? AND source_term = ? AND language_code != ?",
        (book_id, term, ALL_LANGUAGES),
    )
    for code, value in translations.items():
        conn.execute(
            "INSERT INTO glossary_terms (book_id, source_term, language_code, preferred_translation) "
            "VALUES (?, ?, ?, ?)",
            (book_id, term, code, value),
        )


def create_term(
    conn: sqlite3.Connection,
    book_id: int,
    *,
    source_term: str,
    explanation: str = "",
    author_notes: str = "",
    keep_unchanged: bool = False,
    translations: dict[str, str] | None = None,
) -> int:
    """Add a term; returns its id."""
    term = _clean_term(source_term)
    cleaned = _clean_translations(conn, book_id, translations or {})
    exists = conn.execute(
        "SELECT 1 FROM glossary_terms WHERE book_id = ? AND source_term = ? AND language_code = ?",
        (book_id, term, ALL_LANGUAGES),
    ).fetchone()
    if exists:
        raise GlossaryError("This term is already in the glossary. Edit the existing entry instead.")
    with conn:
        cur = conn.execute(
            "INSERT INTO glossary_terms (book_id, source_term, language_code, explanation, keep_unchanged, "
            "author_notes) VALUES (?, ?, ?, ?, ?, ?)",
            (book_id, term, ALL_LANGUAGES, explanation.strip(), int(keep_unchanged), author_notes.strip()),
        )
        _write_translations(conn, book_id, term, cleaned)
    return int(cur.lastrowid)


def update_term(
    conn: sqlite3.Connection,
    book_id: int,
    term_id: int,
    *,
    source_term: str,
    explanation: str = "",
    author_notes: str = "",
    keep_unchanged: bool = False,
    translations: dict[str, str] | None = None,
) -> None:
    """Replace a term's settings and translations (the term text itself may change too)."""
    current = get_term(conn, book_id, term_id)
    term = _clean_term(source_term)
    cleaned = _clean_translations(conn, book_id, translations or {})
    if term != current.source_term:
        clash = conn.execute(
            "SELECT 1 FROM glossary_terms WHERE book_id = ? AND source_term = ? AND language_code = ?",
            (book_id, term, ALL_LANGUAGES),
        ).fetchone()
        if clash:
            raise GlossaryError("Another glossary entry already uses this term.")
    with conn:
        conn.execute(
            "DELETE FROM glossary_terms WHERE book_id = ? AND source_term = ? AND language_code != ?",
            (book_id, current.source_term, ALL_LANGUAGES),
        )
        conn.execute(
            "UPDATE glossary_terms SET source_term = ?, explanation = ?, author_notes = ?, keep_unchanged = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (term, explanation.strip(), author_notes.strip(), int(keep_unchanged), term_id),
        )
        _write_translations(conn, book_id, term, cleaned)


def delete_term(conn: sqlite3.Connection, book_id: int, term_id: int) -> None:
    """Remove a term and all its translations."""
    term = get_term(conn, book_id, term_id)
    with conn:
        conn.execute("DELETE FROM glossary_terms WHERE book_id = ? AND source_term = ?", (book_id, term.source_term))


def terms_for_translation(conn: sqlite3.Connection, book_id: int, language_code: str) -> list[GlossaryTerm]:
    """Terms that matter when translating into a language: kept unchanged, or with a preferred wording."""
    return [t for t in list_terms(conn, book_id) if t.keep_unchanged or language_code in t.translations]
