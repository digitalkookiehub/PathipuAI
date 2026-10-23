import dataclasses

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_settings
from app.api.main import create_app
from app.services import chapters, glossary, ocr, review
from app.services.books import create_book
from app.services.publishing import model as publishing
from app.services.translation import review as tr_review
from app.services.translation import service as tr
from app.services.translation.mock import MockProvider
from app.services.translation.prompt import build_system_prompt
from app.services.translation.script import letter_counts, stray_letters, untranslated_reason

TAMIL = "இன்றைக்கும் பாபா நம்முடனிருந்து நமக்கு உதவி செய்கிறார் என்பதை மக்கள் அறிந்து வைத்திருக்கிறார்கள்"
TELUGU = "ఈ రోజుకూ బాబా మనతోనే ఉండి మనకు సహాయం చేస్తున్నారని ప్రజలకు తెలుసు, ఆయన కృప ఎల్లప్పుడూ ఉంటుంది"
ENGLISH = "Even today Baba is with us and helps us, and people know that his grace is always present"
NO_SLEEP = lambda seconds: None  # noqa: E731


# --- detecting the wrong language -------------------------------------------------------------------------------


def test_letters_are_counted_by_script():
    counts = letter_counts("தமிழ் తెలుగు हिन्दी English 123 !?")
    assert set(counts) == {"ta", "te", "hi", "en"} and counts["en"] == 7


def test_tamil_in_a_telugu_book_is_caught():
    reason = untranslated_reason(TAMIL, "ta", "te")
    assert reason and "mostly in Tamil" in reason and "Telugu" in reason
    assert untranslated_reason(TELUGU, "ta", "te") is None
    assert untranslated_reason(ENGLISH, "ta", "te") == "This part does not look like Telugu text."
    assert untranslated_reason(ENGLISH, "ta", "en") is None
    assert untranslated_reason(TAMIL, "ta", "en") and untranslated_reason(TAMIL, "ta", "hi")


def test_short_texts_and_kept_terms_are_not_judged():
    assert untranslated_reason("ஸ்ரீ ஸாயி பாபா", "ta", "te") is None  # a heading is too short to judge
    mantra = "ஓம் நமோ பகவதே வாசுதேவாய"
    mixed = f"{TELUGU} {mantra} {mantra}"
    assert untranslated_reason(mixed, "ta", "te") is None  # a little Tamil is fine
    heavy = f"{mantra} {mantra} {mantra} {mantra} {TELUGU}"
    assert untranslated_reason(heavy, "ta", "te") is not None
    assert untranslated_reason(heavy, "ta", "te", ignore=[mantra]) is None  # glossary "keep unchanged" terms


def test_the_prompt_asks_for_the_target_language_every_time():
    request = tr.TranslationRequest(text="x", source_language="ta", target_language="te")
    assert "Every sentence of your reply must be written in Telugu" in build_system_prompt(request)
    assert "IMPORTANT" not in build_system_prompt(request)
    again = dataclasses.replace(request, previous_failed=True)
    assert "IMPORTANT: your previous answer was not written in Telugu" in build_system_prompt(again)


# --- translating ------------------------------------------------------------------------------------------------


class Scripted:
    name = "scripted"
    is_test = False

    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []

    def translate(self, request):
        self.requests.append(request)
        return self.answers.pop(0) if self.answers else TELUGU


@pytest.fixture
def settings(settings):
    return dataclasses.replace(settings, translation_max_attempts=3)


@pytest.fixture
def book_id(conn, settings, make_pdf):
    book = create_book(
        conn,
        settings,
        title="B",
        author="A",
        description="",
        source_language="ta",
        publication_details="",
        pdf_bytes=make_pdf(2),
    )
    ocr.process_book(conn, settings, book, recognizer=lambda i, s, lang: (TAMIL, 90.0), skip_setup_check=True)
    chapters.create_chapter(conn, book, title="ஒன்று", start_page=1, end_page=2, heading="தலைப்பு")
    review.approve_range(conn, book, 1, 2)
    tr.set_targets(conn, book, ["te"])
    return book


@pytest.fixture
def chapter_id(conn, book_id):
    return chapters.list_chapters(conn, book_id)[0]["id"]


def run(conn, settings, book_id, provider):
    prepared = tr.prepare(conn, settings, book_id)
    return tr.run(conn, settings, book_id, prepared.pairs, provider, sleep=NO_SLEEP)


def body(conn, chapter_id):
    return conn.execute("SELECT * FROM translations WHERE chapter_id = ? AND chunk_index = 1", (chapter_id,)).fetchone()


def test_a_tamil_answer_is_asked_for_again_with_a_firmer_instruction(conn, settings, book_id, chapter_id):
    provider = Scripted(["Heading", TAMIL, TELUGU])  # the body part comes back in Tamil once
    summary = run(conn, settings, book_id, provider)
    assert (summary.completed, summary.failed) == (2, 0)
    assert [r.previous_failed for r in provider.requests] == [False, False, True]
    row = body(conn, chapter_id)
    assert row["translated_text"] == TELUGU and row["attempts"] == 2 and row["status"] == "awaiting_approval"


def test_an_answer_that_stays_tamil_fails_clearly_instead_of_being_saved(conn, settings, book_id, chapter_id):
    provider = Scripted(["Heading", TAMIL, TAMIL, TAMIL])
    summary = run(conn, settings, book_id, provider)
    assert (summary.completed, summary.failed) == (1, 1)
    row = body(conn, chapter_id)
    assert row["status"] == "failed" and row["translated_text"] is None
    assert "still mostly in Tamil" in row["error"] and "Gave up after 3 tries" in row["error"]
    assert len(provider.requests) == 4


def test_test_mode_is_not_judged_as_a_translation(conn, settings, book_id, chapter_id):
    summary = run(conn, settings, book_id, MockProvider())
    assert summary.failed == 0 and body(conn, chapter_id)["status"] == "awaiting_approval"
    assert tr.overview(conn, settings, book_id)[0].languages["te"].untranslated == 0


# --- parts that are already saved in the wrong language (like the book in the bug report) ------------------------


def test_a_saved_tamil_part_cannot_be_approved_or_published_and_is_fixed_by_translating_again(
    conn, settings, book_id, chapter_id
):
    run(conn, settings, book_id, Scripted(["Heading", TELUGU]))
    conn.execute("UPDATE translations SET translated_text = ?, status = 'approved' WHERE chunk_index = 1", (TAMIL,))
    conn.execute("UPDATE translations SET status = 'approved' WHERE chunk_index = 0")
    conn.commit()  # as in the bug report: Tamil text sitting in a translation that was approved

    cell = tr.overview(conn, settings, book_id)[0].languages["te"]
    assert cell.untranslated == 1
    problems = publishing.publication_status(conn, settings, book_id).languages["te"].problems
    assert any("not in Telugu" in p for p in problems)
    with pytest.raises(publishing.PublishError, match="not in Telugu"):
        publishing.build_publication(conn, settings, book_id, "target", ["te"])

    conn.execute("UPDATE translations SET status = 'awaiting_approval' WHERE chunk_index = 1")
    conn.commit()
    with pytest.raises(tr_review.ReviewBlocked, match="still mostly in Tamil"):
        tr_review.approve_chunk(conn, settings, book_id, chapter_id, "te", 1)
    assert tr_review.approve_all(conn, settings, book_id, chapter_id, "te") == (0, 1)  # the Tamil part is skipped

    fixed = tr.prepare(conn, settings, book_id)  # no confirmation: it was never a real translation
    assert fixed.pending_chunks == 1
    assert tr_review.get_chunk(conn, book_id, chapter_id, "te", 0)["status"] == "approved"  # the good part is kept
    tr.run(conn, settings, book_id, fixed.pairs, Scripted([TELUGU]), sleep=NO_SLEEP)
    assert tr.overview(conn, settings, book_id)[0].languages["te"].untranslated == 0
    tr_review.approve_chunk(conn, settings, book_id, chapter_id, "te", 1)


def test_the_authors_own_edits_are_never_replaced_automatically(conn, settings, book_id, chapter_id):
    run(conn, settings, book_id, Scripted(["Heading", TAMIL.replace("இன்றைக்கும்", "இன்று")]))
    conn.execute("UPDATE translations SET edited_text = 'my own wording' WHERE chunk_index = 1")
    conn.commit()
    assert tr.prepare(conn, settings, book_id).pending_chunks == 0
    assert body(conn, chapter_id)["edited_text"] == "my own wording"


def test_kept_glossary_terms_do_not_count_as_untranslated(conn, settings, book_id, chapter_id):
    glossary.create_term(conn, book_id, source_term="நமோ பகவதே வாசுதேவாய ஓம் நமோ", keep_unchanged=True)
    text = TELUGU + " நமோ பகவதே வாசுதேவாய ஓம் நமோ நமோ பகவதே வாசுதேவாய ஓம் நமோ"
    run(conn, settings, book_id, Scripted(["Heading", text]))
    assert tr.overview(conn, settings, book_id)[0].languages["te"].untranslated == 0


def test_api_flags_untranslated_parts(conn, settings, book_id, chapter_id):
    run(conn, settings, book_id, Scripted(["Heading", TELUGU]))
    conn.execute("UPDATE translations SET translated_text = ? WHERE chunk_index = 1", (TAMIL,))
    conn.commit()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    base = f"/api/books/{book_id}"
    chunks = client.get(f"{base}/chapters/{chapter_id}/translation/te").json()
    assert [c["untranslated"] for c in chunks] == [False, True]
    cell = client.get(f"{base}/translation").json()["chapters"][0]["languages"]["te"]
    assert cell["untranslated"] == 1
    blocked = client.post(f"{base}/chapters/{chapter_id}/translation/te/1/approve")
    assert blocked.status_code == 400 and "still mostly in Tamil" in blocked.json()["detail"]


# --- letters from another script (a Gujarati letter slipped into Telugu) -----------------------------------------

STRAY = TELUGU[:20] + "ષે" + TELUGU[20:]  # Gujarati ષ (U+0AB7) and ે (U+0AC7), as in the report


def test_letters_of_another_script_are_found():
    assert stray_letters(STRAY, "ta", "te") == ["ષ", "ે"]
    assert stray_letters(TELUGU, "ta", "te") == []
    assert stray_letters(f"{TELUGU} ஓம் நமோ", "ta", "te") == []  # the book's own script (kept terms) is fine
    assert stray_letters(f"{TELUGU} Om 123 ॥", "ta", "te") == []  # Latin, digits and the danda punctuation are fine


def test_a_translation_with_a_stray_letter_is_asked_for_again(conn, settings, book_id, chapter_id):
    provider = Scripted(["Heading", STRAY, TELUGU])
    summary = run(conn, settings, book_id, provider)
    assert (summary.completed, summary.failed) == (2, 0)
    assert [r.previous_failed for r in provider.requests] == [False, False, True]
    assert body(conn, chapter_id)["translated_text"] == TELUGU


def test_a_saved_stray_letter_is_named_with_its_place_when_exporting(conn, settings, book_id, chapter_id):
    run(conn, settings, book_id, Scripted(["Heading", TELUGU]))
    conn.execute("UPDATE translations SET translated_text = ?, status = 'approved' WHERE chunk_index = 1", (STRAY,))
    conn.execute("UPDATE translations SET status = 'approved' WHERE chunk_index = 0")
    conn.commit()
    with pytest.raises(publishing.PublishError) as caught:
        publishing.build_publication(conn, settings, book_id, "target", ["te"])
    message = str(caught.value)
    assert "U+0AB7" in message and "near “…" in message and "Review translations" in message
