import dataclasses
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.api import translation_jobs
from app.api.deps import get_settings
from app.api.main import create_app
from app.services import chapters, ocr, review
from app.services.books import create_book
from app.services.translation.base import PermanentProviderError


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
        pdf_bytes=make_pdf(4),
    )
    counter = iter(range(1, 100))
    ocr.process_book(
        conn,
        settings,
        book,
        recognizer=lambda i, s, lang: (f"பத்தி {next(counter)}\n\nமற்றொரு பத்தி", 90.0),
        skip_setup_check=True,
    )
    chapters.create_chapter(conn, book, title="ஒன்று", start_page=1, end_page=2)
    chapters.create_chapter(conn, book, title="இரண்டு", start_page=3, end_page=4)
    return book


@pytest.fixture
def client(settings):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def wait_until_idle(client, book_id):
    for _ in range(300):
        state = client.get(f"/api/books/{book_id}/translation").json()
        if not state["running"]:
            return state
        time.sleep(0.05)
    raise AssertionError("translation did not finish")


def test_provider_and_targets(client, book_id):
    provider = client.get("/api/translation/provider").json()
    assert provider["name"] == "mock" and provider["ready"] and provider["is_test"]

    targets = client.get(f"/api/books/{book_id}/targets").json()
    assert targets["selected"] == [] and "ta" not in [lang["code"] for lang in targets["available"]]
    assert len(targets["available"]) == 5
    assert client.put(f"/api/books/{book_id}/targets", json={"languages": []}).status_code == 400
    assert client.put(f"/api/books/{book_id}/targets", json={"languages": ["ta"]}).status_code == 400
    chosen = client.put(f"/api/books/{book_id}/targets", json={"languages": ["te", "hi"]}).json()
    assert chosen["selected"] == ["te", "hi"]


def test_bulk_approve_endpoint(client, book_id):
    base = f"/api/books/{book_id}/pages/approve"
    assert client.post(base, json={"first_page": 1, "last_page": 3}).json() == {"approved": 3, "unread": 0}
    assert client.post(base, json={"first_page": 1, "last_page": 3}).json() == {"approved": 0, "unread": 0}
    assert client.post(base, json={"first_page": 1, "last_page": 99}).status_code == 400
    assert client.post(base, json={"first_page": 3, "last_page": 1}).status_code == 400
    assert client.get(f"/api/books/{book_id}/ocr").json()["review_counts"]["approved"] == 3


def test_full_translation_flow(client, book_id):
    base = f"/api/books/{book_id}"
    first = client.get(f"{base}/chapters").json()["chapters"][0]["id"]
    assert client.post(f"{base}/translation", json={}).status_code == 400  # no languages chosen yet
    client.put(f"{base}/targets", json={"languages": ["te"]})

    not_ready = client.post(f"{base}/translation", json={"chapter_ids": [first]})
    assert not_ready.status_code == 400 and "not approved yet" in not_ready.json()["detail"]
    state = client.get(f"{base}/translation").json()
    assert [c["ready"] for c in state["chapters"]] == [False, False]

    client.post(f"{base}/pages/approve", json={"first_page": 1, "last_page": 2})
    started = client.post(f"{base}/translation", json={})
    assert started.status_code == 202 and started.json()["status"] == "started" and started.json()["chunks"] == 2
    assert [s["title"] for s in started.json()["skipped"]] == ["இரண்டு"]
    state = wait_until_idle(client, book_id)
    assert state["error"] is None and state["job"]["status"] == "done" and state["job"]["completed"] == 2
    chapter = state["chapters"][0]
    assert chapter["ready"] and chapter["languages"]["te"]["status"] == "awaiting_approval"
    assert state["chapters"][1]["languages"]["te"]["status"] == "not_started"

    chunks = client.get(f"{base}/chapters/{first}/translation/te").json()
    assert [c["chunk_index"] for c in chunks] == [0, 1]
    assert chunks[0]["translated_text"] == "[Telugu test translation] ஒன்று"
    assert chunks[1]["provider"] == "mock" and chunks[1]["source_text"].startswith("பத்தி 1")
    assert client.get(f"{base}/chapters/{first}/translation/xx").status_code == 400

    again = client.post(f"{base}/translation", json={}).json()
    assert again["status"] == "nothing_to_do"  # finished chunks are never translated again


def test_approved_translations_need_confirmation(client, conn, book_id):
    base = f"/api/books/{book_id}"
    client.put(f"{base}/targets", json={"languages": ["te"]})
    client.post(f"{base}/pages/approve", json={"first_page": 1, "last_page": 4})
    client.post(f"{base}/translation", json={})
    wait_until_idle(client, book_id)
    conn.execute("UPDATE translations SET status = 'approved'")
    conn.commit()
    review.save_corrected_text(conn, book_id, 1, "மாற்றப்பட்ட உரை")
    review.approve_page(conn, book_id, 1)

    blocked = client.post(f"{base}/translation", json={})
    assert blocked.status_code == 409
    assert blocked.json()["needs_confirmation"] is True and "approved or edited" in blocked.json()["detail"]
    assert client.get(f"{base}/translation").json()["chapters"][0]["languages"]["te"]["outdated"] is True

    confirmed = client.post(f"{base}/translation", json={"overwrite": True})
    assert confirmed.status_code == 202
    wait_until_idle(client, book_id)
    assert client.get(f"{base}/translation").json()["chapters"][0]["languages"]["te"]["status"] == "awaiting_approval"


def test_provider_not_ready_changes_nothing(book_id, conn, settings):
    broken = dataclasses.replace(settings, translation_provider="claude", translation_api_key="")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: broken
    client = TestClient(app)
    base = f"/api/books/{book_id}"
    client.put(f"{base}/targets", json={"languages": ["te"]})
    client.post(f"{base}/pages/approve", json={"first_page": 1, "last_page": 4})
    response = client.post(f"{base}/translation", json={})
    assert response.status_code == 400
    assert conn.execute("SELECT COUNT(*) FROM translations").fetchone()[0] == 0
    assert client.get("/api/translation/provider").json()["ready"] is False


def test_only_one_job_per_book_and_fatal_errors_are_reported(client, book_id, monkeypatch):
    base = f"/api/books/{book_id}"
    client.put(f"{base}/targets", json={"languages": ["te"]})
    client.post(f"{base}/pages/approve", json={"first_page": 1, "last_page": 4})
    gate = threading.Event()

    class Blocking:
        name = "blocking"
        is_test = True

        def translate(self, request):
            gate.wait(10)
            raise PermanentProviderError("The translation service rejected the key.", fatal=True)

    monkeypatch.setattr("app.api.translation_routes.get_provider", lambda settings: Blocking())
    assert client.post(f"{base}/translation", json={}).status_code == 202
    assert client.get(f"{base}/translation").json()["running"] is True
    second = client.post(f"{base}/translation", json={})
    assert second.status_code == 400 and "already being translated" in second.json()["detail"]
    gate.set()
    state = wait_until_idle(client, book_id)
    assert state["error"] == "The translation service rejected the key."
    assert state["job"]["status"] == "failed" and translation_jobs.is_running(book_id) is False


def test_real_provider_replaces_earlier_test_mode_results(client, book_id, monkeypatch):
    base = f"/api/books/{book_id}"
    client.put(f"{base}/targets", json={"languages": ["te"]})
    client.post(f"{base}/pages/approve", json={"first_page": 1, "last_page": 4})
    client.post(f"{base}/translation", json={})  # test mode (the mock provider)
    state = wait_until_idle(client, book_id)
    assert state["chapters"][0]["languages"]["te"]["test_output"] is True
    assert client.post(f"{base}/translation", json={}).json()["status"] == "nothing_to_do"

    class Real:
        name = "real"
        is_test = False

        def translate(self, request):
            return f"REAL({request.text[:6]})"

    monkeypatch.setattr("app.api.translation_routes.get_provider", lambda settings: Real())
    started = client.post(f"{base}/translation", json={})
    assert started.status_code == 202 and started.json()["status"] == "started"
    state = wait_until_idle(client, book_id)
    cell = state["chapters"][0]["languages"]["te"]
    assert cell["test_output"] is False and cell["status"] == "awaiting_approval"
    chapter = state["chapters"][0]["id"]
    chunks = client.get(f"{base}/chapters/{chapter}/translation/te").json()
    assert all(c["translated_text"].startswith("REAL(") and c["provider"] == "real" for c in chunks)
