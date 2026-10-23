import dataclasses

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_settings
from app.api.main import create_app
from app.services import chapters, glossary, ocr, review
from app.services.books import create_book
from app.services.translation import review as tr_review
from app.services.translation import service as tr
from app.services.translation.base import PermanentProviderError
from app.services.translation.mock import MockProvider

NO_SLEEP = lambda seconds: None  # noqa: E731


@pytest.fixture
def settings(settings):
    return dataclasses.replace(settings, translation_max_attempts=2)


class Recorder:
    """A 'real' provider (not test mode) that returns scripted or default text."""

    name = "recorder"
    is_test = False

    def __init__(self, script=None):
        self.script = list(script or [])

    def translate(self, request):
        if self.script:
            action = self.script.pop(0)
            if isinstance(action, Exception):
                raise action
            return action
        return f"T({request.text[:12]})"


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
        pdf_bytes=make_pdf(3),
    )
    counter = iter(range(1, 100))
    ocr.process_book(
        conn,
        settings,
        book,
        recognizer=lambda i, s, lang: (f"பத்தி {next(counter)}\n\nமற்றொரு பத்தி", 90.0),
        skip_setup_check=True,
    )
    chapters.create_chapter(conn, book, title="ஒன்று", start_page=1, end_page=3, heading="தலைப்பு")
    review.approve_range(conn, book, 1, 3)
    tr.set_targets(conn, book, ["te"])
    return book


@pytest.fixture
def chapter_id(conn, book_id):
    return chapters.list_chapters(conn, book_id)[0]["id"]


def translate(conn, settings, book_id, provider):
    prepared = tr.prepare(conn, settings, book_id)
    tr.run(conn, settings, book_id, prepared.pairs, provider, sleep=NO_SLEEP)


def chunk(conn, book_id, chapter_id, index):
    return tr_review.get_chunk(conn, book_id, chapter_id, "te", index)


def test_edit_keeps_the_machine_translation_and_needs_approval_again(conn, settings, book_id, chapter_id):
    translate(conn, settings, book_id, Recorder(["Heading", "Body machine text"]))
    tr_review.approve_chunk(conn, settings, book_id, chapter_id, "te", 1)
    assert chunk(conn, book_id, chapter_id, 1)["status"] == "approved"

    status = tr_review.save_edit(conn, settings, book_id, chapter_id, "te", 1, "Body, corrected by the author")
    row = chunk(conn, book_id, chapter_id, 1)
    assert status == "awaiting_approval" and row["status"] == "awaiting_approval"
    assert row["translated_text"] == "Body machine text" and row["edited_text"] == "Body, corrected by the author"
    assert tr_review.current_text(row) == "Body, corrected by the author"
    approved_at = conn.execute("SELECT approved_at FROM translations WHERE id = ?", (row["id"],)).fetchone()[0]
    assert approved_at is None


def test_saving_unchanged_or_machine_text_stores_no_edit(conn, settings, book_id, chapter_id):
    translate(conn, settings, book_id, Recorder(["Heading", "Body"]))
    tr_review.approve_chunk(conn, settings, book_id, chapter_id, "te", 1)
    assert tr_review.save_edit(conn, settings, book_id, chapter_id, "te", 1, "Body") == "approved"  # no change
    tr_review.save_edit(conn, settings, book_id, chapter_id, "te", 1, "Changed")
    tr_review.save_edit(conn, settings, book_id, chapter_id, "te", 1, "Body")  # back to the machine text
    row = chunk(conn, book_id, chapter_id, 1)
    assert row["edited_text"] is None and row["status"] == "awaiting_approval"


def test_empty_and_untranslated_parts_cannot_be_edited(conn, settings, book_id, chapter_id):
    tr.prepare(conn, settings, book_id)  # chunks exist but nothing is translated yet
    with pytest.raises(tr_review.ReviewBlocked, match="not been translated"):
        tr_review.save_edit(conn, settings, book_id, chapter_id, "te", 1, "text")
    with pytest.raises(tr_review.ReviewBlocked, match="not been translated"):
        tr_review.approve_chunk(conn, settings, book_id, chapter_id, "te", 1)
    tr.run(conn, settings, book_id, [(chapter_id, "te")], Recorder(), sleep=NO_SLEEP)
    with pytest.raises(tr_review.ReviewBlocked, match="cannot be empty"):
        tr_review.save_edit(conn, settings, book_id, chapter_id, "te", 1, "   ")
    with pytest.raises(tr.TranslationError, match="not found"):
        tr_review.get_chunk(conn, book_id, chapter_id, "te", 99)


def test_test_mode_placeholders_can_never_be_approved(conn, settings, book_id, chapter_id):
    translate(conn, settings, book_id, MockProvider())
    with pytest.raises(tr_review.ReviewBlocked, match="test-mode placeholder"):
        tr_review.approve_chunk(conn, settings, book_id, chapter_id, "te", 1)
    assert tr_review.approve_all(conn, settings, book_id, chapter_id, "te") == (0, 2)
    assert chunk(conn, book_id, chapter_id, 1)["status"] == "awaiting_approval"


def test_outdated_parts_cannot_be_approved_until_translated_again(conn, settings, book_id, chapter_id):
    translate(conn, settings, book_id, Recorder())
    assert tr_review.outdated_indexes(conn, settings, book_id, chapter_id) == set()
    review.save_corrected_text(conn, book_id, 2, "வேறு உரை")  # the Tamil changes...
    review.approve_page(conn, book_id, 2)  # ...and is approved again
    assert tr_review.outdated_indexes(conn, settings, book_id, chapter_id) == {1}
    with pytest.raises(tr_review.ReviewBlocked, match="Tamil text changed"):
        tr_review.approve_chunk(conn, settings, book_id, chapter_id, "te", 1)
    tr_review.approve_chunk(conn, settings, book_id, chapter_id, "te", 0)  # the heading is still current
    tr.prepare(conn, settings, book_id)  # translating again refreshes the changed part
    tr.run(conn, settings, book_id, [(chapter_id, "te")], Recorder(), sleep=NO_SLEEP)
    tr_review.approve_chunk(conn, settings, book_id, chapter_id, "te", 1)
    assert tr_review.outdated_indexes(conn, settings, book_id, chapter_id) == set()


def test_restore_returns_to_the_machine_translation(conn, settings, book_id, chapter_id):
    translate(conn, settings, book_id, Recorder(["Heading", "Machine"]))
    tr_review.save_edit(conn, settings, book_id, chapter_id, "te", 1, "My version")
    tr_review.approve_chunk(conn, settings, book_id, chapter_id, "te", 1)
    tr_review.restore_machine(conn, settings, book_id, chapter_id, "te", 1)
    row = chunk(conn, book_id, chapter_id, 1)
    assert row["edited_text"] is None and row["status"] == "awaiting_approval"
    assert tr_review.current_text(row) == "Machine"


def test_approve_all_skips_what_cannot_be_approved(conn, settings, book_id, chapter_id):
    provider = Recorder(["Heading", PermanentProviderError("declined")])
    translate(conn, settings, book_id, provider)  # the body part failed
    assert tr_review.approve_all(conn, settings, book_id, chapter_id, "te") == (1, 1)
    assert chunk(conn, book_id, chapter_id, 0)["status"] == "approved"
    assert chunk(conn, book_id, chapter_id, 1)["status"] == "failed"
    tr.prepare(conn, settings, book_id)
    tr.run(conn, settings, book_id, [(chapter_id, "te")], Recorder(), sleep=NO_SLEEP)
    assert tr_review.approve_all(conn, settings, book_id, chapter_id, "te") == (1, 0)
    assert tr_review.approve_all(conn, settings, book_id, chapter_id, "te") == (0, 0)
    state = tr.overview(conn, settings, book_id)[0].languages["te"]
    assert state.status == "approved" and state.approved == state.total == 2


def test_glossary_warnings_follow_the_edit(conn, settings, book_id, chapter_id):
    glossary.create_term(conn, book_id, source_term="பத்தி", keep_unchanged=True)
    translate(conn, settings, book_id, Recorder(["Heading", "ఈ అనువాదం ఆ పదాన్ని వదిలివేసింది అందుకే హెచ్చరిక చూపబడుతుంది"]))
    assert "should stay unchanged" in chunk(conn, book_id, chapter_id, 1)["notes"]
    tr_review.save_edit(conn, settings, book_id, chapter_id, "te", 1, "ఈ అనువాదం ఆ పదాన్ని ఉంచుతుంది பத்தி సరిగ్గా అలాగే ఉంటుంది")
    assert chunk(conn, book_id, chapter_id, 1)["notes"] is None
    tr_review.restore_machine(conn, settings, book_id, chapter_id, "te", 1)
    assert "should stay unchanged" in chunk(conn, book_id, chapter_id, 1)["notes"]


def test_review_actions_are_recorded_in_the_history(conn, settings, book_id, chapter_id):
    translate(conn, settings, book_id, Recorder(["Heading", "Machine"]))
    tr_review.save_edit(conn, settings, book_id, chapter_id, "te", 1, "Edited")
    tr_review.approve_chunk(conn, settings, book_id, chapter_id, "te", 1)
    tr_review.restore_machine(conn, settings, book_id, chapter_id, "te", 1)
    rows = conn.execute(
        "SELECT action, old_text, new_text FROM text_history WHERE entity_type = 'translation' ORDER BY id"
    ).fetchall()
    assert [r["action"] for r in rows] == ["translation_edit", "translation_approve", "translation_restore"]
    assert (rows[0]["old_text"], rows[0]["new_text"]) == ("Machine", "Edited")


# --- HTTP API -------------------------------------------------------------------------------------------------


@pytest.fixture
def client(settings):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_review_endpoints(client, conn, settings, book_id, chapter_id):
    translate(conn, settings, book_id, Recorder(["Heading", "Machine text"]))
    base = f"/api/books/{book_id}/chapters/{chapter_id}/translation/te"

    listed = client.get(base).json()
    assert [c["chunk_index"] for c in listed] == [0, 1] and not any(c["outdated"] for c in listed)

    edited = client.put(f"{base}/1/text", json={"text": "Author wording"})
    assert edited.status_code == 200
    assert edited.json()["edited_text"] == "Author wording" and edited.json()["status"] == "awaiting_approval"
    assert edited.json()["translated_text"] == "Machine text"

    approved = client.post(f"{base}/1/approve").json()
    assert approved["status"] == "approved"
    assert client.put(f"{base}/1/text", json={"text": "Changed again"}).json()["status"] == "awaiting_approval"
    assert client.post(f"{base}/1/restore").json()["edited_text"] is None
    assert client.post(f"{base}/approve-all").json() == {"approved": 2, "skipped": 0}
    assert client.get(f"{base}").json()[1]["status"] == "approved"


def test_review_endpoint_errors_are_friendly(client, conn, settings, book_id, chapter_id):
    translate(conn, settings, book_id, MockProvider())
    base = f"/api/books/{book_id}/chapters/{chapter_id}/translation/te"
    blocked = client.post(f"{base}/1/approve")
    assert blocked.status_code == 400 and "test-mode placeholder" in blocked.json()["detail"]
    assert client.put(f"{base}/1/text", json={"text": " "}).status_code == 400
    assert client.put(f"{base}/9/text", json={"text": "x"}).status_code == 400
    assert client.post(f"/api/books/{book_id}/chapters/{chapter_id}/translation/xx/approve-all").status_code == 400
    assert client.post(f"{base}/approve-all").json() == {"approved": 0, "skipped": 2}
