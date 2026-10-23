import dataclasses

import pytest

from app.services import chapters, glossary, ocr, review
from app.services.books import create_book
from app.services.translation import (
    ProviderSetupError,
    get_provider,
    provider_status,
)
from app.services.translation import service as tr
from app.services.translation.base import (
    PermanentProviderError,
    TransientProviderError,
)
from app.services.translation.chunking import paragraphs_of, split_into_chunks, text_hash
from app.services.translation.mock import MockProvider


@pytest.fixture
def settings(settings):
    return dataclasses.replace(settings, translation_max_attempts=4, translation_backoff_seconds=2.0)


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
        pdf_bytes=make_pdf(6),
    )
    calls = {"n": 0}

    def recognizer(image, s, lang):
        calls["n"] += 1
        return f"பத்தி A{calls['n']}\nவரி இரண்டு\n\nபத்தி B{calls['n']}", 90.0

    ocr.process_book(conn, settings, book, recognizer=recognizer, skip_setup_check=True)
    chapters.create_chapter(conn, book, title="ஒன்று", start_page=1, end_page=3, heading="முதல் அத்தியாயம்")
    chapters.create_chapter(conn, book, title="இரண்டு", start_page=4, end_page=6)
    return book


def approve(conn, book_id, first, last):
    review.approve_range(conn, book_id, first, last)


class Recorder:
    """A provider that records requests and can be told to fail."""

    name = "recorder"
    is_test = True

    def __init__(self, script=None):
        self.requests = []
        self.script = list(script or [])  # exceptions or strings, used in order; empty means succeed

    def translate(self, request):
        self.requests.append(request)
        if self.script:
            action = self.script.pop(0)
            if isinstance(action, Exception):
                raise action
            return action
        return f"తెలుగు అనువాదం ({len(request.text)})"


NO_SLEEP = lambda seconds: None  # noqa: E731


def statuses(conn, chapter_id, language):
    return [
        r["status"]
        for r in conn.execute(
            "SELECT status FROM translations WHERE chapter_id = ? AND language_code = ? ORDER BY chunk_index",
            (chapter_id, language),
        )
    ]


# --- target languages -----------------------------------------------------------------------------------------


def test_set_targets_validation_and_order(conn, book_id):
    assert tr.set_targets(conn, book_id, ["te", "hi", "te"]) == ["te", "hi"]
    assert tr.set_targets(conn, book_id, ["en", "te"]) == ["te", "en"]  # hi removed, te keeps its place
    with pytest.raises(tr.TranslationError, match="at least one"):
        tr.set_targets(conn, book_id, [])
    with pytest.raises(tr.TranslationError, match="own language"):
        tr.set_targets(conn, book_id, ["ta"])
    with pytest.raises(tr.TranslationError, match="not supported"):
        tr.set_targets(conn, book_id, ["xx"])
    assert tr.get_targets(conn, book_id) == ["te", "en"]  # failed attempts changed nothing


# --- chunking -------------------------------------------------------------------------------------------------


def test_chunking_keeps_paragraphs_and_order():
    pages = ["A1\nA2\n\nB1", "C1\n\nD1"]
    assert paragraphs_of(pages) == ["A1\nA2", "B1", "C1", "D1"]
    assert split_into_chunks(pages, 1000) == ["A1\nA2\n\nB1\n\nC1\n\nD1"]
    chunks = split_into_chunks(pages, 8)
    assert chunks == ["A1\nA2", "B1\n\nC1", "D1"]
    assert "\n\n".join(chunks).replace("\n\n", "\n").split("\n") == ["A1", "A2", "B1", "C1", "D1"]


def test_chunking_splits_oversized_paragraphs():
    sentence = "வணக்கம் நண்பர்களே. "
    paragraph = sentence * 30
    chunks = split_into_chunks([paragraph], 100)
    assert len(chunks) > 3 and all(len(c) <= 100 for c in chunks)
    assert "".join(chunks).replace(" ", "").replace("\n", "") == paragraph.replace(" ", "")
    no_space = "அ" * 250
    assert [len(c) for c in split_into_chunks([no_space], 100)] == [100, 100, 50]
    assert split_into_chunks([], 100) == [] and split_into_chunks(["  \n\n "], 100) == []


def test_text_hash_is_stable():
    assert text_hash("வணக்கம்") == text_hash("வணக்கம்")
    assert text_hash("a") != text_hash("b")


# --- prepare --------------------------------------------------------------------------------------------------


def test_prepare_needs_targets_and_chapters(conn, settings, book_id):
    with pytest.raises(tr.TranslationError, match="choose the languages"):
        tr.prepare(conn, settings, book_id)
    tr.set_targets(conn, book_id, ["te"])
    with pytest.raises(tr.TranslationError, match="No chapter is ready"):
        tr.prepare(conn, settings, book_id)
    with pytest.raises(tr.TranslationError, match="under 'Translate into'"):
        tr.prepare(conn, settings, book_id, languages=["hi"])


def test_only_approved_text_is_prepared(conn, settings, book_id):
    tr.set_targets(conn, book_id, ["te"])
    approve(conn, book_id, 1, 2)  # chapter one is missing page 3
    first = chapters.list_chapters(conn, book_id)[0]["id"]
    with pytest.raises(tr.TranslationError, match="not approved yet: 3"):
        tr.prepare(conn, settings, book_id, chapter_ids=[first])
    assert conn.execute("SELECT COUNT(*) FROM translations").fetchone()[0] == 0
    approve(conn, book_id, 3, 3)
    prepared = tr.prepare(conn, settings, book_id)  # no explicit chapters: unready ones are skipped
    assert [s["title"] for s in prepared.skipped] == ["இரண்டு"]
    assert prepared.pairs == [(first, "te")]
    rows = conn.execute("SELECT chunk_index, source_text FROM translations ORDER BY chunk_index").fetchall()
    assert rows[0]["source_text"] == "முதல் அத்தியாயம்"  # the heading is chunk 0
    assert "பத்தி A1" in rows[1]["source_text"] and "பத்தி A3" in rows[1]["source_text"]
    assert "A4" not in rows[1]["source_text"]
    assert prepared.pending_chunks == len(rows)


def test_editing_an_approved_page_blocks_translation_until_reapproved(conn, settings, book_id):
    tr.set_targets(conn, book_id, ["te"])
    approve(conn, book_id, 1, 3)
    review.save_corrected_text(conn, book_id, 2, "திருத்தப்பட்டது")  # no longer approved
    first = chapters.list_chapters(conn, book_id)[0]["id"]
    with pytest.raises(tr.TranslationError, match="not approved yet: 2"):
        tr.prepare(conn, settings, book_id, chapter_ids=[first])


# --- run ------------------------------------------------------------------------------------------------------


def prepared_run(conn, settings, book_id, provider, languages=("te",), approve_to=3):
    tr.set_targets(conn, book_id, list(languages))
    approve(conn, book_id, 1, approve_to)
    prepared = tr.prepare(conn, settings, book_id)
    return prepared, tr.run(conn, settings, book_id, prepared.pairs, provider, sleep=NO_SLEEP)


def test_mock_run_translates_everything_and_marks_provider(conn, settings, book_id):
    progress = []
    tr.set_targets(conn, book_id, ["te", "en"])
    approve(conn, book_id, 1, 3)
    prepared = tr.prepare(conn, settings, book_id)
    summary = tr.run(
        conn,
        settings,
        book_id,
        prepared.pairs,
        MockProvider(),
        progress=lambda d, t: progress.append((d, t)),
        sleep=NO_SLEEP,
    )
    assert summary.failed == 0 and summary.completed == summary.total == prepared.pending_chunks == 4
    assert progress[-1] == (4, 4)
    rows = conn.execute("SELECT * FROM translations ORDER BY language_code, chunk_index").fetchall()
    assert {r["status"] for r in rows} == {"awaiting_approval"} and {r["provider"] for r in rows} == {"mock"}
    heading = next(r for r in rows if r["chunk_index"] == 0 and r["language_code"] == "te")
    assert heading["translated_text"] == "[Telugu test translation] முதல் அத்தியாயம்"
    job = conn.execute("SELECT * FROM processing_jobs WHERE job_type = 'translation'").fetchone()
    assert (job["status"], job["total"], job["completed"], job["failed"]) == ("done", 4, 4, 0)


def test_heading_request_is_marked_and_glossary_passed(conn, settings, book_id):
    glossary.create_term(conn, book_id, source_term="பத்தி", keep_unchanged=True)
    glossary.create_term(conn, book_id, source_term="வரி", translations={"te": "పంక్తి"})
    glossary.create_term(conn, book_id, source_term="இல்லாதது", keep_unchanged=True)  # not in the text
    provider = Recorder()
    prepared_run(conn, settings, book_id, provider)
    heading, body = provider.requests
    assert heading.is_heading and heading.glossary == () and not body.is_heading
    terms = {(e.term, e.keep_unchanged, e.preferred) for e in body.glossary}
    assert terms == {("பத்தி", True, None), ("வரி", False, "పంక్తి")}
    assert body.source_language == "ta" and body.target_language == "te"


def test_finished_chunks_are_never_translated_again(conn, settings, book_id):
    first_provider = Recorder()
    first_provider.script = ["heading done", PermanentProviderError("This passage was declined.")]
    prepared, summary = prepared_run(conn, settings, book_id, first_provider)
    chapter = prepared.pairs[0][0]
    assert (summary.completed, summary.failed, summary.aborted) == (1, 1, None)
    assert statuses(conn, chapter, "te") == ["awaiting_approval", "failed"]
    failed = conn.execute("SELECT error FROM translations WHERE status = 'failed'").fetchone()
    assert failed["error"] == "This passage was declined."

    again = Recorder()
    prepared_again = tr.prepare(conn, settings, book_id)  # same source: nothing is reset
    assert prepared_again.pending_chunks == 1
    summary = tr.run(conn, settings, book_id, prepared_again.pairs, again, sleep=NO_SLEEP)
    assert len(again.requests) == 1
    assert summary.completed == 1 and statuses(conn, chapter, "te") == ["awaiting_approval"] * 2
    third = Recorder()
    assert tr.run(conn, settings, book_id, prepared_again.pairs, third, sleep=NO_SLEEP).total == 0
    assert third.requests == []


def test_interrupted_chunks_are_resumed(conn, settings, book_id):
    tr.set_targets(conn, book_id, ["te"])
    approve(conn, book_id, 1, 3)
    prepared = tr.prepare(conn, settings, book_id)
    conn.execute("UPDATE translations SET status = 'processing'")  # a crash left these behind
    conn.commit()
    provider = Recorder()
    summary = tr.run(conn, settings, book_id, prepared.pairs, provider, sleep=NO_SLEEP)
    assert summary.completed == 2 and len(provider.requests) == 2


def test_transient_errors_are_retried_with_backoff(conn, settings, book_id):
    sleeps = []
    tr.set_targets(conn, book_id, ["te"])
    approve(conn, book_id, 1, 3)
    prepared = tr.prepare(conn, settings, book_id)
    provider = Recorder([TransientProviderError("busy"), TransientProviderError("busy", retry_after=7), "ok", "ok2"])
    summary = tr.run(conn, settings, book_id, prepared.pairs, provider, sleep=sleeps.append)
    assert summary.completed == 2 and summary.failed == 0
    assert 7 <= sleeps[1] < 7.3 and 2 <= sleeps[0] < 2.3  # backoff, then the server's retry-after
    row = conn.execute("SELECT attempts, translated_text FROM translations WHERE chunk_index = 0").fetchone()
    assert (row["attempts"], row["translated_text"]) == (3, "ok")


def test_retries_are_bounded(conn, settings, book_id):
    sleeps = []
    tr.set_targets(conn, book_id, ["te"])
    approve(conn, book_id, 1, 3)
    prepared = tr.prepare(conn, settings, book_id)
    provider = Recorder([TransientProviderError("The translation service is busy.")] * 4)
    summary = tr.run(conn, settings, book_id, prepared.pairs, provider, sleep=sleeps.append)
    assert (summary.failed, summary.completed) == (1, 1)  # the second chunk succeeds afterwards
    assert len(sleeps) == 3 and len(provider.requests) == 5
    error = conn.execute("SELECT error, attempts FROM translations WHERE status = 'failed'").fetchone()
    assert "Gave up after 4 tries" in error["error"] and error["attempts"] == 4


def test_a_fatal_error_stops_the_run_and_leaves_the_rest_waiting(conn, settings, book_id):
    tr.set_targets(conn, book_id, ["te", "en"])
    approve(conn, book_id, 1, 3)
    prepared = tr.prepare(conn, settings, book_id)
    provider = Recorder([PermanentProviderError("The translation service rejected the key.", fatal=True)])
    summary = tr.run(conn, settings, book_id, prepared.pairs, provider, sleep=NO_SLEEP)
    assert summary.aborted == "The translation service rejected the key." and len(provider.requests) == 1
    chapter = prepared.pairs[0][0]
    assert statuses(conn, chapter, "te") == ["failed", "not_started"]
    assert set(statuses(conn, chapter, "en")) == {"not_started"}
    job = conn.execute("SELECT status, error FROM processing_jobs WHERE job_type = 'translation'").fetchone()
    assert job["status"] == "failed" and "rejected the key" in job["error"]


def test_glossary_warnings_are_recorded(conn, settings, book_id):
    glossary.create_term(conn, book_id, source_term="பத்தி", keep_unchanged=True)
    glossary.create_term(conn, book_id, source_term="வரி", translations={"te": "పంక్తి"})
    provider = Recorder(["heading", "a translation that dropped everything"])
    prepared_run(conn, settings, book_id, provider)
    notes = conn.execute("SELECT notes FROM translations WHERE chunk_index = 1").fetchone()["notes"]
    assert '"பத்தி" should stay unchanged' in notes and '"పంక్తి" for "வரி" was not found' in notes
    assert conn.execute("SELECT notes FROM translations WHERE chunk_index = 0").fetchone()["notes"] is None


def test_mock_keeps_protected_terms_so_no_warning(conn, settings, book_id):
    glossary.create_term(conn, book_id, source_term="பத்தி", keep_unchanged=True)
    prepared_run(conn, settings, book_id, MockProvider())
    assert conn.execute("SELECT COUNT(*) FROM translations WHERE notes IS NOT NULL").fetchone()[0] == 0


# --- changed source and protection of approved work -----------------------------------------------------------


def test_changed_source_resets_only_changed_chunks(conn, settings, book_id):
    prepared, _ = prepared_run(conn, settings, book_id, Recorder())
    chapter = prepared.pairs[0][0]
    review.save_corrected_text(conn, book_id, 2, "புதிய உரை")
    review.approve_page(conn, book_id, 2)
    result = tr.prepare(conn, settings, book_id)  # nothing was approved or edited, so no confirmation needed
    assert result.pending_chunks == 1
    assert statuses(conn, chapter, "te") == ["awaiting_approval", "not_started"]  # the heading is untouched
    assert conn.execute("SELECT translated_text FROM translations WHERE chunk_index = 1").fetchone()[0] is None


def test_approved_translations_need_confirmation_to_be_replaced(conn, settings, book_id):
    prepared, _ = prepared_run(conn, settings, book_id, Recorder())
    conn.execute("UPDATE translations SET status = 'approved', approved_at = datetime('now')")
    conn.commit()
    assert tr.prepare(conn, settings, book_id).pending_chunks == 0  # unchanged source: approved work is kept
    review.save_corrected_text(conn, book_id, 1, "மாறிய உரை")
    review.approve_page(conn, book_id, 1)
    with pytest.raises(tr.NeedsConfirmation, match="1 approved or edited part"):
        tr.prepare(conn, settings, book_id)
    assert set(statuses(conn, prepared.pairs[0][0], "te")) == {"approved"}  # nothing was touched
    tr.prepare(conn, settings, book_id, overwrite=True)
    assert statuses(conn, prepared.pairs[0][0], "te") == ["approved", "not_started"]


def test_hand_edited_translations_are_protected_too(conn, settings, book_id):
    prepared_run(conn, settings, book_id, Recorder())
    conn.execute("UPDATE translations SET edited_text = 'my own wording' WHERE chunk_index = 1")
    conn.commit()
    review.save_corrected_text(conn, book_id, 3, "மாறிய உரை")
    review.approve_page(conn, book_id, 3)
    with pytest.raises(tr.NeedsConfirmation):
        tr.prepare(conn, settings, book_id)
    tr.prepare(conn, settings, book_id, overwrite=True)
    assert conn.execute("SELECT edited_text FROM translations WHERE chunk_index = 1").fetchone()[0] is None


def test_unselected_language_translations_are_kept(conn, settings, book_id):
    prepared_run(conn, settings, book_id, Recorder(), languages=("te", "en"))
    tr.set_targets(conn, book_id, ["en"])
    assert conn.execute("SELECT COUNT(*) FROM translations WHERE language_code = 'te'").fetchone()[0] == 2


# --- overview -------------------------------------------------------------------------------------------------


def test_overview_reports_readiness_and_status(conn, settings, book_id):
    tr.set_targets(conn, book_id, ["te", "en"])
    approve(conn, book_id, 1, 2)
    first, second = chapters.list_chapters(conn, book_id)
    before = tr.overview(conn, settings, book_id)
    assert [(c.ready, c.missing_pages) for c in before] == [(False, [3]), (False, [4, 5, 6])]
    assert before[0].languages["te"].status == "not_started"

    approve(conn, book_id, 3, 3)
    prepared = tr.prepare(conn, settings, book_id, languages=["te"])
    provider = Recorder()
    provider.script = ["heading", PermanentProviderError("declined")]
    tr.run(conn, settings, book_id, prepared.pairs, provider, sleep=NO_SLEEP)
    state = tr.overview(conn, settings, book_id)[0]
    assert state.ready and state.languages["te"].status == "failed" and state.languages["te"].failed == 1
    assert state.languages["te"].error == "declined" and state.languages["en"].status == "not_started"

    tr.run(conn, settings, book_id, prepared.pairs, Recorder(), sleep=NO_SLEEP)
    assert tr.overview(conn, settings, book_id)[0].languages["te"].status == "awaiting_approval"
    conn.execute("UPDATE translations SET status = 'approved'")
    conn.commit()
    done = tr.overview(conn, settings, book_id)[0].languages["te"]
    assert (done.status, done.approved, done.translated, done.total, done.outdated) == ("approved", 2, 2, 2, False)
    review.save_corrected_text(conn, book_id, 1, "வேறு உரை")
    review.approve_page(conn, book_id, 1)
    assert tr.overview(conn, settings, book_id)[0].languages["te"].outdated is True
    assert second["id"] == tr.overview(conn, settings, book_id)[1].id


def test_list_chunks_returns_source_and_translation(conn, settings, book_id):
    prepared, _ = prepared_run(conn, settings, book_id, MockProvider())
    chapter = prepared.pairs[0][0]
    chunks = tr.list_chunks(conn, book_id, chapter, "te")
    assert [c["chunk_index"] for c in chunks] == [0, 1]
    assert chunks[1]["translated_text"].startswith("[Telugu test translation] ")
    with pytest.raises(chapters.ChapterError):
        tr.list_chunks(conn, book_id, 9999, "te")


# --- provider selection ---------------------------------------------------------------------------------------


def test_provider_status_and_selection(settings, monkeypatch):
    mock = provider_status(settings)
    assert mock.ready and mock.is_test and "placeholders" in mock.message
    assert isinstance(get_provider(settings), MockProvider)

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    claude = dataclasses.replace(settings, translation_provider="claude", translation_api_key="")
    status = provider_status(claude)
    if status.message and "not installed" not in status.message:
        assert not status.ready and "TRANSLATION_API_KEY" in status.message
    with pytest.raises(ProviderSetupError):
        get_provider(claude)

    unknown = dataclasses.replace(settings, translation_provider="babel")
    assert not provider_status(unknown).ready and "Unknown translation provider" in provider_status(unknown).message


# --- placeholder (test mode) output ---------------------------------------------------------------------------


def test_test_mode_output_is_replaced_by_a_real_provider_without_confirmation(conn, settings, book_id):
    prepared, _ = prepared_run(conn, settings, book_id, MockProvider())
    chapter = prepared.pairs[0][0]
    assert tr.overview(conn, settings, book_id)[0].languages["te"].test_output is True
    conn.execute("UPDATE translations SET status = 'approved'")  # even if it was approved, it is only a placeholder
    conn.commit()

    assert tr.prepare(conn, settings, book_id).pending_chunks == 0  # still in test mode: results are kept
    redo = tr.prepare(conn, settings, book_id, replace_test_output=True)  # no NeedsConfirmation
    assert redo.pending_chunks == 2 and statuses(conn, chapter, "te") == ["not_started"] * 2
    assert conn.execute("SELECT COUNT(*) FROM translations WHERE translated_text IS NOT NULL").fetchone()[0] == 0

    real = Recorder()
    tr.run(conn, settings, book_id, redo.pairs, real, sleep=NO_SLEEP)
    assert len(real.requests) == 2
    state = tr.overview(conn, settings, book_id)[0].languages["te"]
    assert state.test_output is False and state.status == "awaiting_approval"


def test_real_translations_are_not_touched_when_a_real_provider_runs_again(conn, settings, book_id):
    prepared_run(conn, settings, book_id, Recorder())
    again = tr.prepare(conn, settings, book_id, replace_test_output=True)
    assert again.pending_chunks == 0 and tr.overview(conn, settings, book_id)[0].languages["te"].test_output is False


def test_hand_edited_test_output_is_also_replaced(conn, settings, book_id):
    prepared_run(conn, settings, book_id, MockProvider())
    conn.execute("UPDATE translations SET edited_text = 'my edit'")
    conn.commit()
    assert tr.prepare(conn, settings, book_id, replace_test_output=True).pending_chunks == 2
