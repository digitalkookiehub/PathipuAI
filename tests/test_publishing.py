import dataclasses
import re
import threading
import time

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_settings
from app.api.main import create_app
from app.services import chapters, ocr, review
from app.services.books import create_book
from app.services.publishing import exports, fonts, model
from app.services.publishing import render as render_module
from app.services.publishing.model import Block, Publication, PublishError, Section, paragraphs
from app.services.translation import review as tr_review
from app.services.translation import service as tr

SAMPLES = {
    "ta": "தமிழ் மொழி மிகவும் இனிமையானது. ஸ்ரீ ஸாயி பாபாவின் 11 உறுதி மொழிகள். க்ஷ ஜ்ஞ",
    "te": "తెలుగు భాష చాలా మధురమైనది. శ్రీ సాయి బాబా యొక్క 11 వాగ్దానాలు. క్ష జ్ఞ",
    "kn": "ಕನ್ನಡ ಭಾಷೆ ಬಹಳ ಸುಂದರವಾಗಿದೆ. ಶ್ರೀ ಸಾಯಿ ಬಾಬಾ ಅವರ 11 ವಚನಗಳು. ಕ್ಷ ಜ್ಞ",
    "ml": "മലയാളം ഭാഷ വളരെ മനോഹരമാണ്. ശ്രീ സായി ബാബയുടെ 11 വചനങ്ങൾ. ക്ഷ ജ്ഞ",
    "hi": "हिन्दी भाषा बहुत सुंदर है। श्री साईं बाबा के ११ वचन। क्ष ज्ञ",
    "en": "The 11 assurances of Sri Sai Baba, 1234567890 (ligatures: fi fl).",
}


def pdf_texts(data: bytes) -> list[str]:
    doc = pdfium.PdfDocument(data)
    try:
        return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
    finally:
        doc.close()


# --- fonts ----------------------------------------------------------------------------------------------------


def test_every_bundled_font_file_exists_and_is_licensed():
    for family in set(fonts.FAMILIES.values()):
        for bold in (False, True):
            assert fonts.font_path(family, bold).is_file(), (family, bold)
    assert (fonts.FONT_DIR / "OFL.txt").read_text(encoding="utf-8").startswith("Copyright")


@pytest.mark.parametrize("language", list(SAMPLES))
def test_fonts_cover_each_language(language):
    assert fonts.missing_glyphs(SAMPLES[language], language) == set()


def test_unsupported_characters_are_detected_and_joiners_ignored():
    assert fonts.missing_glyphs("ok 😀 中", "ta") == {"😀", "中"}
    assert fonts.missing_glyphs("ம்‌ம ‍­\n\t", "ta") == set()
    assert fonts.missing_glyphs("Tamil text with Latin letters and 123", "ta") == set()  # Latin fallback


def test_paragraph_joining():
    text = "first line\nsecond line\n\n\nsecond paragraph\n  wrapped  \n\n  "
    assert paragraphs(text) == ["first line second line", "second paragraph wrapped"]
    assert paragraphs("   ") == []


# --- layout ---------------------------------------------------------------------------------------------------


def publication(kind="source", languages=(), sections=None, toc=True, sample=False):
    sections = sections or [
        Section([Block("Chapter One", "en")], [Block("First paragraph of the book.", "en")]),
    ]
    return Publication("My Book", "An Author", "Edition 1", "en", kind, list(languages), sections, toc, sample)


@pytest.mark.parametrize("language", list(SAMPLES))
def test_pdf_is_made_for_every_supported_script(language):
    section = Section([Block(SAMPLES[language], language)], [Block(SAMPLES[language] * 8, language)])
    pub = publication(kind="target", languages=[language], sections=[section])
    pub.source_language = language
    pub.title = SAMPLES[language]
    data, pages = render_module.render_pdf(pub)
    assert data.startswith(b"%PDF") and pages >= 3  # cover, contents, chapter
    assert fonts.family_for(language).encode() in data  # the right font was embedded
    doc = pdfium.PdfDocument(data)
    image = doc[2].render(scale=1).to_pil().convert("L")
    assert image.getextrema()[0] < 80  # dark ink was drawn: the page is not blank
    doc.close()


def test_latin_text_is_extractable_and_page_numbers_are_drawn():
    data, pages = render_module.render_pdf(publication())
    texts = pdf_texts(data)
    assert len(texts) == pages == 3
    assert "My Book" in texts[0] and "An Author" in texts[0] and "Edition 1" in texts[0]
    assert "Contents" in texts[1] and "Chapter One" in texts[1]
    assert "Chapter One" in texts[2] and "First paragraph of the book." in texts[2]
    assert "1" not in texts[0].replace("Edition 1", "")  # no page number on the cover
    assert "2" in texts[1].split() and texts[2].split()[-1] == "3"  # footers on the contents and chapter pages


def test_contents_page_numbers_match_the_chapters_even_when_they_span_pages():
    sections = [Section([Block(f"Heading {n:02d}", "en")], [Block("Body text.", "en")]) for n in range(1, 61)]
    data, pages = render_module.render_pdf(publication(sections=sections))
    texts = pdf_texts(data)
    contents_pages = [i for i, t in enumerate(texts) if i > 0 and "Body text." not in t]
    assert len(contents_pages) >= 2  # 60 chapters do not fit on one contents page
    listed = {}
    for text in (texts[i] for i in contents_pages):
        for match in re.finditer(r"(Heading \d\d)\s+(\d+)\s*$", text, flags=re.MULTILINE):
            listed[match.group(1)] = int(match.group(2))
    assert len(listed) == 60
    for name, number in listed.items():
        assert name in texts[number - 1] and "Body text." in texts[number - 1], (name, number)
    assert pages == 1 + len(contents_pages) + 60  # no blank pages


def test_contents_can_be_left_out_and_sample_is_marked():
    data, pages = render_module.render_pdf(publication(toc=False, sample=True))
    texts = pdf_texts(data)
    assert pages == 2 and not any("Contents" in t for t in texts)
    assert "Sample preview" in texts[0] and "SAMPLE PREVIEW" in texts[1]


def test_page_references_and_labels_are_drawn():
    section = Section(
        [Block("Heading", "en")],
        [Block("Page 12", "en", "pageref"), Block("Body.", "en"), Block("Telugu", "en", "label"), Block("x", "en")],
    )
    texts = pdf_texts(render_module.render_pdf(publication(sections=[section], toc=False))[0])
    assert "[ Page 12 ]" in texts[1] and "TELUGU" in texts[1]


# --- readiness and the "only approved text" rules --------------------------------------------------------------


class Translator:
    """A real (non-test) provider that returns fixed text per language."""

    name = "translator"
    is_test = False
    words = {"te": "తెలుగు అనువాదం", "hi": "हिन्दी अनुवाद"}

    def translate(self, request):
        return f"{self.words[request.target_language]} {len(request.text)}\n\n{self.words[request.target_language]} 2"


@pytest.fixture
def settings(settings):
    return dataclasses.replace(settings, translation_max_attempts=2)


@pytest.fixture
def book_id(conn, settings, make_pdf):
    book = create_book(
        conn,
        settings,
        title="நூல் தலைப்பு",
        author="ஆசிரியர்",
        description="",
        source_language="ta",
        publication_details="முதல் பதிப்பு",
        pdf_bytes=make_pdf(6),
    )
    counter = iter(range(1, 100))
    ocr.process_book(
        conn,
        settings,
        book,
        recognizer=lambda i, s, lang: (f"பத்தி {next(counter)}\nவரி இரண்டு\n\nமற்றொரு பத்தி", 90.0),
        skip_setup_check=True,
    )
    chapters.create_chapter(conn, book, title="ஒன்று", start_page=1, end_page=3, heading="முதல் அத்தியாயம்")
    chapters.create_chapter(conn, book, title="இரண்டு", start_page=4, end_page=6)
    review.approve_range(conn, book, 1, 6)
    tr.set_targets(conn, book, ["te", "hi"])
    return book


@pytest.fixture
def translated(conn, settings, book_id):
    prepared = tr.prepare(conn, settings, book_id)
    tr.run(conn, settings, book_id, prepared.pairs, Translator(), sleep=lambda s: None)
    return prepared.pairs


def approve_translations(conn, settings, book_id):
    for chapter in chapters.list_chapters(conn, book_id):
        for code in ("te", "hi"):
            tr_review.approve_all(conn, settings, book_id, chapter["id"], code)


def test_status_reports_what_is_missing(conn, settings, book_id):
    status = model.publication_status(conn, settings, book_id)
    assert status.source.ready and status.chapters == 2 and status.unassigned == []
    assert not status.languages["te"].ready and "not translated yet" in status.languages["te"].problems[0]


def test_status_follows_translation_review(conn, settings, book_id, translated):
    problems = model.publication_status(conn, settings, book_id).languages["te"].problems
    assert any("not approved yet" in p for p in problems)
    approve_translations(conn, settings, book_id)
    status = model.publication_status(conn, settings, book_id)
    assert status.languages["te"].ready and status.languages["hi"].ready
    review.save_corrected_text(conn, book_id, 1, "மாற்றப்பட்ட உரை")  # the Tamil changes after translating
    stale = model.publication_status(conn, settings, book_id)
    assert not stale.source.ready and "pages 1 are not approved" in stale.source.problems[0]
    review.approve_page(conn, book_id, 1)
    assert any("Tamil changed" in p for p in model.publication_status(conn, settings, book_id).languages["te"].problems)


def test_placeholders_and_unassigned_pages(conn, settings, book_id, translated):
    approve_translations(conn, settings, book_id)
    conn.execute("UPDATE translations SET provider = 'mock' WHERE language_code = 'te'")
    conn.commit()
    assert any("placeholders" in p for p in model.publication_status(conn, settings, book_id).languages["te"].problems)
    chapter = chapters.list_chapters(conn, book_id)[1]
    chapters.update_chapter(conn, book_id, chapter["id"], end_page=5)
    assert model.publication_status(conn, settings, book_id).unassigned == [(6, 6)]


def test_source_edition_contains_only_approved_text(conn, settings, book_id):
    pub = model.build_publication(conn, settings, book_id, "source", page_references=True)
    assert [s.headings[0].text for s in pub.sections] == ["முதல் அத்தியாயம்", "இரண்டு"]  # heading, else title
    first = pub.sections[0].blocks
    assert first[0] == Block("Page 1", "en", "pageref")
    assert Block("பத்தி 1 வரி இரண்டு", "ta") in first and Block("மற்றொரு பத்தி", "ta") in first
    assert pub.title == "நூல் தலைப்பு" and pub.details == "முதல் பதிப்பு"

    review.save_corrected_text(conn, book_id, 5, "SECRET-UNAPPROVED")
    with pytest.raises(PublishError, match="Chapter 2.*pages 5 are not approved"):
        model.build_publication(conn, settings, book_id, "source")
    sample = model.build_publication(conn, settings, book_id, "source", sample=True)  # chapter 1 only
    assert len(sample.sections) == 1
    data, _ = render_module.render_pdf(sample)
    assert not any("SECRET-UNAPPROVED" in t for t in pdf_texts(data))


def test_translation_editions_need_approved_current_translations(conn, settings, book_id, translated):
    with pytest.raises(PublishError, match="not approved yet"):
        model.build_publication(conn, settings, book_id, "target", ["te"])
    approve_translations(conn, settings, book_id)
    target = model.build_publication(conn, settings, book_id, "target", ["te"])
    heading = target.sections[0].headings
    assert [h.language for h in heading] == ["te"] and heading[0].text.startswith("తెలుగు అనువాదం")
    assert all(b.language == "te" for b in target.sections[0].blocks)

    bilingual = model.build_publication(conn, settings, book_id, "bilingual", ["hi"])
    assert [h.language for h in bilingual.sections[0].headings] == ["ta", "hi"]
    roles = [(b.role, b.language) for b in bilingual.sections[0].blocks]
    assert roles[0] == ("source", "ta") and ("main", "hi") in roles and not any(r[1] == "te" for r in roles)

    multi = model.build_publication(conn, settings, book_id, "multilingual")  # all chosen languages by default
    assert multi.languages == ["te", "hi"]
    blocks = multi.sections[0].blocks
    labels = [b.text for b in blocks if b.role == "label"]
    assert labels[:2] == ["Telugu", "Hindi"]
    assert [b.language for b in blocks if b.role == "source"][:1] == ["ta"]


def test_unapproved_tamil_makes_its_translation_outdated_and_blocks_publishing(conn, settings, book_id, translated):
    approve_translations(conn, settings, book_id)
    assert model.build_publication(conn, settings, book_id, "target", ["te"]) is not None
    review.save_corrected_text(conn, book_id, 5, "not approved any more")  # a page of chapter 2 changes
    with pytest.raises(PublishError, match="Tamil changed after 1 part"):
        model.build_publication(conn, settings, book_id, "target", ["te"])
    sample = model.build_publication(conn, settings, book_id, "target", ["te"], sample=True)  # chapter 1 is fine
    assert len(sample.sections) == 1


def test_choices_are_validated(conn, settings, book_id, translated):
    approve_translations(conn, settings, book_id)
    for kind, languages, message in [
        ("magic", [], "choose what to publish"),
        ("target", [], "exactly one language"),
        ("bilingual", ["te", "hi"], "exactly one language"),
        ("target", ["en"], "not one of the languages"),
    ]:
        with pytest.raises(PublishError, match=message):
            model.build_publication(conn, settings, book_id, kind, languages)


def test_publishing_needs_chapters(conn, settings, make_pdf):
    book = create_book(
        conn,
        settings,
        title="X",
        author="",
        description="",
        source_language="ta",
        publication_details="",
        pdf_bytes=make_pdf(1),
    )
    with pytest.raises(PublishError, match="Create the chapters"):
        model.build_publication(conn, settings, book, "source")
    assert not model.publication_status(conn, settings, book).source.ready


def test_sample_needs_only_the_first_chapter_and_is_short(conn, settings, book_id, translated):
    tr_review.approve_all(conn, settings, book_id, chapters.list_chapters(conn, book_id)[0]["id"], "te")
    sample = model.build_publication(conn, settings, book_id, "target", ["te"], sample=True)  # chapter 2 not approved
    assert len(sample.sections) == 1 and sample.sample
    full_blocks = len([b for b in sample.sections[0].blocks])
    assert full_blocks <= 2 * model.SAMPLE_PARTS


def test_characters_the_fonts_cannot_draw_block_publishing(conn, settings, book_id):
    review.save_corrected_text(conn, book_id, 2, "வணக்கம் 😀")
    review.approve_page(conn, book_id, 2)
    with pytest.raises(PublishError, match="empty boxes") as caught:
        model.build_publication(conn, settings, book_id, "source")
    assert "Tamil" in str(caught.value) and "U+1F600" in str(caught.value)


# --- exports --------------------------------------------------------------------------------------------------


def test_export_is_stored_listed_downloaded_and_deleted(conn, settings, book_id):
    export_id = exports.start_export(conn, settings, book_id, "source", background=False)
    [row] = exports.list_exports(conn, book_id)
    assert row["status"] == "done" and row["page_count"] >= 4 and row["size_bytes"] > 1000
    path = exports.export_file(conn, settings, book_id, export_id)
    assert path.read_bytes().startswith(b"%PDF") and path.parent.name == "exports"
    assert path.name == f"source-{export_id}.pdf"

    other = create_book(
        conn,
        settings,
        title="Other",
        author="",
        description="",
        source_language="ta",
        publication_details="",
        pdf_bytes=_pdf(),
    )
    with pytest.raises(PublishError, match="not found"):
        exports.export_file(conn, settings, other, export_id)  # another book's export is not reachable
    conn.execute("UPDATE export_jobs SET file_name = '../../../outside.pdf' WHERE id = ?", (export_id,))
    conn.commit()
    with pytest.raises(PublishError, match="missing"):
        exports.export_file(conn, settings, book_id, export_id)  # only the bare file name is ever used
    conn.execute("UPDATE export_jobs SET file_name = ? WHERE id = ?", (path.name, export_id))
    conn.commit()
    exports.delete_export(conn, settings, book_id, export_id)
    assert not path.exists() and exports.list_exports(conn, book_id) == []


def _pdf():
    import io

    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(100, 700, "x")
    pdf.save()
    return buffer.getvalue()


def test_export_files_are_named_by_kind_language_and_id(conn, settings, book_id, translated):
    approve_translations(conn, settings, book_id)
    a = exports.start_export(conn, settings, book_id, "bilingual", ["hi"], background=False)
    b = exports.start_export(conn, settings, book_id, "multilingual", background=False, sample=True, toc=False)
    names = {r["id"]: r["file_name"] for r in exports.list_exports(conn, book_id)}
    assert names[a] == f"bilingual-hi-{a}.pdf" and names[b] == f"multilingual-te-hi-sample-{b}.pdf"


def test_a_stopped_server_does_not_leave_exports_hanging(conn, settings, book_id):
    conn.execute(
        "INSERT INTO export_jobs (book_id, export_type, status) VALUES (?, 'source', 'processing')", (book_id,)
    )
    conn.commit()
    [row] = exports.list_exports(conn, book_id)
    assert row["status"] == "failed" and "server stopped" in row["error"]


def test_only_one_pdf_is_made_at_a_time_and_failures_are_friendly(conn, settings, book_id, monkeypatch):
    gate = threading.Event()
    real = render_module.render_pdf

    def slow(publication):
        gate.wait(10)
        return real(publication)

    monkeypatch.setattr(exports, "render_pdf", slow)
    exports.start_export(conn, settings, book_id, "source")
    assert exports.is_running(book_id)
    with pytest.raises(PublishError, match="already being created"):
        exports.start_export(conn, settings, book_id, "source")
    with pytest.raises(PublishError, match="still being created"):
        exports.delete_export(conn, settings, book_id, exports.list_exports(conn, book_id)[0]["id"])
    gate.set()
    for _ in range(100):
        if not exports.is_running(book_id):
            break
        time.sleep(0.1)
    assert exports.list_exports(conn, book_id)[0]["status"] == "done"

    def broken(publication):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(exports, "render_pdf", broken)
    failed_id = exports.start_export(conn, settings, book_id, "source", background=False)
    row = next(r for r in exports.list_exports(conn, book_id) if r["id"] == failed_id)
    assert row["status"] == "failed" and "secret" not in row["error"] and "try again" in row["error"]


# --- HTTP API -------------------------------------------------------------------------------------------------


@pytest.fixture
def client(settings):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def wait_done(client, book_id):
    for _ in range(300):
        rows = client.get(f"/api/books/{book_id}/exports").json()
        if rows and rows[0]["status"] != "processing":
            return rows[0]
        time.sleep(0.1)
    raise AssertionError("export did not finish")


def test_publishing_endpoints(client, conn, settings, book_id, translated):
    status = client.get(f"/api/books/{book_id}/publishing").json()
    assert status["chapters"] == 2 and status["source"]["ready"] and not status["languages"]["te"]["ready"]

    refused = client.post(f"/api/books/{book_id}/exports", json={"kind": "target", "languages": ["te"]})
    assert refused.status_code == 400 and "Only approved text is published" in refused.json()["detail"]
    assert client.post(f"/api/books/{book_id}/exports", json={"kind": "nonsense"}).status_code == 422

    approve_translations(conn, settings, book_id)
    created = client.post(
        f"/api/books/{book_id}/exports", json={"kind": "bilingual", "languages": ["te"], "sample": True}
    )
    assert created.status_code == 202
    row = wait_done(client, book_id)
    assert row["status"] == "done" and row["kind"] == "bilingual" and row["languages"] == ["te"] and row["sample"]
    base = f"/api/books/{book_id}/exports/{row['id']}/file"
    shown = client.get(base)
    assert shown.status_code == 200 and shown.headers["content-type"] == "application/pdf"
    assert shown.content.startswith(b"%PDF") and shown.headers["content-disposition"].startswith("inline")
    saved = client.get(base, params={"download": True})
    assert saved.headers["content-disposition"].startswith("attachment")
    assert client.get(f"/api/books/{book_id}/exports/999/file").status_code == 400
    assert client.delete(f"/api/books/{book_id}/exports/{row['id']}").status_code == 204
    assert client.get(f"/api/books/{book_id}/exports").json() == []


def test_kept_unchanged_tamil_terms_can_appear_inside_other_scripts():
    mixed = "తెలుగు వాక్యం ஸ்ரீ ஸாயி பாபா మళ్ళీ తెలుగు. Page 12."
    assert fonts.missing_glyphs(mixed, "te") != set()  # the Telugu font alone cannot draw the Tamil word
    assert fonts.missing_glyphs(mixed, "te", source_language="ta") == set()
    pub = publication(
        kind="target", languages=["te"], sections=[Section([Block(mixed, "te")], [Block(mixed * 3, "te")])]
    )
    pub.source_language = "ta"
    data, _ = render_module.render_pdf(pub)
    assert data.startswith(b"%PDF") and b"NotoSansTamil" in data and b"NotoSansTelugu" in data
    assert fonts.missing_glyphs("ok 😀", "te", source_language="ta") == {"😀"}  # real gaps are still caught


def test_numbered_items_start_new_paragraphs_when_asked():
    text = "3\n1 ஷீர்டி தலத்தை\nஎவன் மிதிக்கிறானோ\n2. இரண்டாவது\nவரி\nஅ) ஸாயி\nஆ) பாபா\n\nஒரு புதிய பத்தி\n10 நீ என்னை"
    assert paragraphs(text) == ["3 1 ஷீர்டி தலத்தை எவன் மிதிக்கிறானோ 2. இரண்டாவது வரி அ) ஸாயி ஆ) பாபா", "ஒரு புதிய பத்தி 10 நீ என்னை"]
    assert paragraphs(text, numbered=True) == [
        "3",
        "1 ஷீர்டி தலத்தை எவன் மிதிக்கிறானோ",
        "2. இரண்டாவது வரி",
        "அ) ஸாயி",
        "ஆ) பாபா",
        "ஒரு புதிய பத்தி",
        "10 நீ என்னை",
    ]
    year = paragraphs("page 5 of the book\n2026 was the year", numbered=True)
    assert year == ["page 5 of the book 2026 was the year"]  # a four-digit year is not a list number
    assert paragraphs("a plain wrapped\nparagraph", numbered=True) == ["a plain wrapped paragraph"]


def test_publication_keeps_verses_apart_unless_told_not_to(conn, settings, book_id):
    review.save_corrected_text(conn, book_id, 1, "1 முதல் வரி\nதொடர்கிறது\n2 இரண்டாம் வரி")
    review.approve_page(conn, book_id, 1)
    apart = model.build_publication(conn, settings, book_id, "source")
    texts = [b.text for b in apart.sections[0].blocks]
    assert "1 முதல் வரி தொடர்கிறது" in texts and "2 இரண்டாம் வரி" in texts
    joined = model.build_publication(conn, settings, book_id, "source", numbered_paragraphs=False)
    assert "1 முதல் வரி தொடர்கிறது 2 இரண்டாம் வரி" in [b.text for b in joined.sections[0].blocks]
