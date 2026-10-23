import time

import pytest
from fastapi.testclient import TestClient

from app.api import jobs
from app.api.deps import get_settings
from app.api.main import create_app
from app.services import ocr


@pytest.fixture
def client(settings, monkeypatch):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    # Tests have no Tesseract: use a fake recognizer and skip the language-data check.
    monkeypatch.setattr("app.api.routes.check_language", lambda s, code: "tam")
    monkeypatch.setattr(ocr, "check_language", lambda s, code: "tam")
    monkeypatch.setattr(ocr, "tesseract_recognize", lambda image, s, lang: ("வணக்கம்", 88.0))
    return TestClient(app)


def upload(client, make_pdf, pages=3, **overrides):
    data = {"title": "My Book", "author": "Guru", "source_language": "ta"}
    data.update(overrides)
    return client.post("/api/books", data=data, files={"file": ("scan.pdf", make_pdf(pages), "application/pdf")})


def wait_for_ocr(client, book_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/books/{book_id}/ocr").json()
        if not status["running"]:
            return status
        time.sleep(0.1)
    raise AssertionError("OCR did not finish")


def test_health_and_languages(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    codes = [lang["code"] for lang in client.get("/api/languages").json()]
    assert codes == ["ta", "te", "kn", "ml", "hi", "en"]


def test_add_list_get_delete_book(client, make_pdf):
    created = upload(client, make_pdf)
    assert created.status_code == 201
    book = created.json()
    assert book["page_count"] == 3 and book["source_language_name"] == "Tamil" and book["status_label"] == "Not started"
    assert [b["id"] for b in client.get("/api/books").json()] == [book["id"]]
    assert client.get(f"/api/books/{book['id']}").json()["title"] == "My Book"
    assert client.delete(f"/api/books/{book['id']}").status_code == 400  # needs confirm
    assert client.delete(f"/api/books/{book['id']}?confirm=true").status_code == 204
    assert client.get(f"/api/books/{book['id']}").status_code == 404


def test_friendly_errors(client, make_pdf):
    bad = client.post(
        "/api/books",
        data={"title": "X", "source_language": "ta"},
        files={"file": ("a.pdf", b"nope", "application/pdf")},
    )
    assert bad.status_code == 400 and "PDF" in bad.json()["detail"]
    assert upload(client, make_pdf).status_code == 201
    assert upload(client, make_pdf).status_code == 400  # duplicate title + author


def test_ocr_flow_review_and_export(client, make_pdf):
    book_id = upload(client, make_pdf).json()["id"]
    assert client.post(f"/api/books/{book_id}/ocr", json={"first_page": 1, "last_page": 2}).status_code == 202
    status = wait_for_ocr(client, book_id)
    assert status["page_counts"]["done"] == 2 and status["job"]["completed"] == 2

    page = client.get(f"/api/books/{book_id}/pages/1").json()
    assert page["text"] == "வணக்கம்" and page["has_image"]
    assert client.get(f"/api/books/{book_id}/pages/1/image").headers["content-type"] == "image/jpeg"

    saved = client.put(f"/api/books/{book_id}/pages/1/text", json={"text": "திருத்தம்"}).json()
    assert saved["review_status"] == "corrected" and saved["ocr_text"] == "வணக்கம்"
    approved = client.post(f"/api/books/{book_id}/pages/1/approve").json()
    assert approved["review_status"] == "approved"
    edited = client.put(f"/api/books/{book_id}/pages/1/text", json={"text": "மீண்டும்"}).json()
    assert edited["review_status"] == "corrected"
    restored = client.post(f"/api/books/{book_id}/pages/1/restore").json()
    assert restored["text"] == "வணக்கம்" and restored["review_status"] == "pending"

    assert [h["page_number"] for h in client.get(f"/api/books/{book_id}/search", params={"q": "வணக்கம்"}).json()] == [
        1,
        2,
    ]
    export = client.get(f"/api/books/{book_id}/export")
    assert export.headers["content-type"].startswith("text/plain")
    assert "--- Page 1 ---" in export.text
    assert "attachment" in export.headers["content-disposition"]


def test_unread_page_cannot_be_approved(client, make_pdf):
    book_id = upload(client, make_pdf).json()["id"]
    response = client.post(f"/api/books/{book_id}/pages/1/approve")
    assert response.status_code == 400 and "not been read" in response.json()["detail"]
    assert client.get(f"/api/books/{book_id}/pages/99").status_code == 404


def test_reread_protects_corrections(client, make_pdf):
    book_id = upload(client, make_pdf, pages=1).json()["id"]
    client.post(f"/api/books/{book_id}/ocr", json={})
    wait_for_ocr(client, book_id)
    client.put(f"/api/books/{book_id}/pages/1/text", json={"text": "my work"})
    blocked = client.post(f"/api/books/{book_id}/ocr/reread", json={"first_page": 1, "last_page": 1})
    assert blocked.status_code == 400
    assert client.get(f"/api/books/{book_id}/pages/1").json()["corrected_text"] == "my work"
    allowed = client.post(
        f"/api/books/{book_id}/ocr/reread", json={"first_page": 1, "last_page": 1, "discard_corrections": True}
    )
    assert allowed.status_code == 202
    wait_for_ocr(client, book_id)
    assert client.get(f"/api/books/{book_id}/pages/1").json()["corrected_text"] is None


def test_invalid_page_range(client, make_pdf):
    book_id = upload(client, make_pdf).json()["id"]
    assert client.post(f"/api/books/{book_id}/ocr", json={"first_page": 5}).status_code == 400
    assert client.post(f"/api/books/{book_id}/ocr", json={"first_page": 3, "last_page": 1}).status_code == 400


def test_second_job_rejected_while_running(client, make_pdf, monkeypatch):
    book_id = upload(client, make_pdf).json()["id"]
    import threading

    gate = threading.Event()
    monkeypatch.setattr(ocr, "tesseract_recognize", lambda image, s, lang: (gate.wait(10) and "x", 50.0))
    assert client.post(f"/api/books/{book_id}/ocr", json={}).status_code == 202
    assert client.get(f"/api/books/{book_id}/ocr").json()["running"] is True
    assert client.post(f"/api/books/{book_id}/ocr", json={}).status_code == 400
    assert client.delete(f"/api/books/{book_id}?confirm=true").status_code == 400
    gate.set()
    wait_for_ocr(client, book_id)
    assert jobs.is_running(book_id) is False


def test_image_path_traversal_blocked(client, make_pdf, conn, settings):
    book_id = upload(client, make_pdf, pages=1).json()["id"]
    client.post(f"/api/books/{book_id}/ocr", json={})
    wait_for_ocr(client, book_id)
    conn.execute("UPDATE book_pages SET image_path = ? WHERE book_id = ?", ("../../../../secret.jpg", book_id))
    conn.commit()
    assert client.get(f"/api/books/{book_id}/pages/1/image").status_code == 404
