import pytest

from app.services import glossary
from app.services.books import create_book, delete_book


@pytest.fixture
def book_id(conn, settings, make_pdf):
    return create_book(
        conn,
        settings,
        title="B",
        author="A",
        description="",
        source_language="ta",
        publication_details="",
        pdf_bytes=make_pdf(1),
    )


def test_create_and_list_term(conn, book_id):
    term_id = glossary.create_term(
        conn,
        book_id,
        source_term="ஓம்",
        explanation="sacred syllable",
        author_notes="never translate",
        keep_unchanged=True,
        translations={"hi": "ॐ", "en": "  "},
    )
    [term] = glossary.list_terms(conn, book_id)
    assert term.id == term_id and term.source_term == "ஓம்" and term.keep_unchanged
    assert term.explanation == "sacred syllable" and term.author_notes == "never translate"
    assert term.translations == {"hi": "ॐ"}  # blank translations are not stored


def test_duplicate_term_rejected(conn, book_id):
    glossary.create_term(conn, book_id, source_term="சமாதி")
    with pytest.raises(glossary.GlossaryError, match="already"):
        glossary.create_term(conn, book_id, source_term=" சமாதி ")


def test_blank_term_and_bad_languages_rejected(conn, book_id):
    with pytest.raises(glossary.GlossaryError):
        glossary.create_term(conn, book_id, source_term="  ")
    with pytest.raises(glossary.GlossaryError, match="not supported"):
        glossary.create_term(conn, book_id, source_term="x", translations={"xx": "y"})
    with pytest.raises(glossary.GlossaryError, match="own language"):
        glossary.create_term(conn, book_id, source_term="x", translations={"ta": "y"})
    assert glossary.list_terms(conn, book_id) == []


def test_update_replaces_translations_and_can_rename(conn, book_id):
    term_id = glossary.create_term(conn, book_id, source_term="பாபா", translations={"en": "Baba", "hi": "बाबा"})
    glossary.update_term(
        conn,
        book_id,
        term_id,
        source_term="ஸாயி பாபா",
        explanation="teacher",
        keep_unchanged=False,
        translations={"te": "బాబా"},
    )
    [term] = glossary.list_terms(conn, book_id)
    assert term.source_term == "ஸாயி பாபா" and term.translations == {"te": "బాబా"} and term.explanation == "teacher"


def test_rename_to_existing_term_rejected(conn, book_id):
    glossary.create_term(conn, book_id, source_term="ஒன்று")
    other = glossary.create_term(conn, book_id, source_term="இரண்டு")
    with pytest.raises(glossary.GlossaryError, match="already uses"):
        glossary.update_term(conn, book_id, other, source_term="ஒன்று")


def test_delete_term_removes_all_rows(conn, book_id):
    term_id = glossary.create_term(conn, book_id, source_term="மந்திரம்", translations={"en": "mantra", "hi": "मंत्र"})
    glossary.delete_term(conn, book_id, term_id)
    assert glossary.list_terms(conn, book_id) == []
    assert conn.execute("SELECT COUNT(*) FROM glossary_terms").fetchone()[0] == 0
    with pytest.raises(glossary.GlossaryError):
        glossary.get_term(conn, book_id, term_id)


def test_terms_for_translation_picks_relevant_terms(conn, book_id):
    glossary.create_term(conn, book_id, source_term="ஓம்", keep_unchanged=True)
    glossary.create_term(conn, book_id, source_term="குரு", translations={"en": "Guru"})
    glossary.create_term(conn, book_id, source_term="வீடு", translations={"hi": "घर"})
    assert [t.source_term for t in glossary.terms_for_translation(conn, book_id, "en")] == ["ஓம்", "குரு"]
    assert [t.source_term for t in glossary.terms_for_translation(conn, book_id, "hi")] == ["ஓம்", "வீடு"]


def test_glossary_deleted_with_book(conn, settings, book_id):
    glossary.create_term(conn, book_id, source_term="ஓம்", translations={"en": "Om"})
    delete_book(conn, settings, book_id)
    assert conn.execute("SELECT COUNT(*) FROM glossary_terms").fetchone()[0] == 0
