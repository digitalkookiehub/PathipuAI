import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_settings
from app.api.main import create_app


@pytest.fixture
def client(settings):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


@pytest.fixture
def book_id(client, make_pdf):
    response = client.post(
        "/api/books",
        data={"title": "B", "author": "A", "source_language": "ta"},
        files={"file": ("a.pdf", make_pdf(6), "application/pdf")},
    )
    return response.json()["id"]


def test_chapter_lifecycle(client, book_id):
    base = f"/api/books/{book_id}/chapters"
    assert client.get(base).json() == {"chapters": [], "unassigned": [[1, 6]]}

    created = client.post(base, json={"title": "One", "start_page": 1, "end_page": 2}).json()
    assert created["unassigned"] == [[3, 6]]
    client.post(base, json={"title": "Two", "heading": "H2", "start_page": 3, "end_page": 4})
    listed = client.get(base).json()["chapters"]
    assert [c["title"] for c in listed] == ["One", "Two"] and listed[1]["heading"] == "H2"
    first, second = listed[0]["id"], listed[1]["id"]

    assert client.post(f"{base}/reorder", json={"chapter_ids": [second, first]}).json()["chapters"][0]["id"] == second
    renamed = client.put(f"{base}/{first}", json={"title": "Renamed", "end_page": 1}).json()
    assert renamed["unassigned"] == [[2, 2], [5, 6]]
    assert [c["title"] for c in renamed["chapters"]] == ["Two", "Renamed"]
    assert client.delete(f"{base}/{second}").json()["unassigned"] == [[2, 6]]


def test_chapter_errors_are_friendly(client, book_id):
    base = f"/api/books/{book_id}/chapters"
    client.post(base, json={"title": "One", "start_page": 1, "end_page": 3})
    clash = client.post(base, json={"title": "Clash", "start_page": 3, "end_page": 4})
    assert clash.status_code == 400 and "already belong" in clash.json()["detail"]
    assert client.post(base, json={"title": "Far", "start_page": 5, "end_page": 20}).status_code == 400
    assert client.put(f"{base}/999", json={"title": "x"}).status_code == 400
    assert client.post(f"{base}/reorder", json={"chapter_ids": [1, 2, 3]}).status_code == 400
    assert client.get("/api/books/999/chapters").status_code == 404


def test_chapter_text_preview_and_export(client, book_id):
    base = f"/api/books/{book_id}/chapters"
    chapter_id = client.post(base, json={"title": "One", "start_page": 1, "end_page": 2}).json()["chapters"][0]["id"]
    assert client.get(f"{base}/{chapter_id}/text").json() == []  # nothing read yet
    export = client.get(f"{base}/{chapter_id}/export")
    assert export.headers["content-type"].startswith("text/plain") and export.text == "One"
    assert "attachment" in export.headers["content-disposition"]


def test_glossary_lifecycle(client, book_id):
    base = f"/api/books/{book_id}/glossary"
    body = {
        "source_term": "ஓம்",
        "explanation": "sacred",
        "keep_unchanged": True,
        "translations": {"hi": "ॐ"},
    }
    created = client.post(base, json=body)
    assert created.status_code == 201 and created.json()["translations"] == {"hi": "ॐ"}
    term_id = created.json()["id"]
    assert client.post(base, json=body).status_code == 400  # duplicate

    body.update(keep_unchanged=False, translations={"en": "Om"})
    updated = client.put(f"{base}/{term_id}", json=body).json()
    assert updated["keep_unchanged"] is False and updated["translations"] == {"en": "Om"}
    assert [t["source_term"] for t in client.get(base).json()] == ["ஓம்"]
    assert client.delete(f"{base}/{term_id}").status_code == 204
    assert client.get(base).json() == []


def test_glossary_validation_errors(client, book_id):
    base = f"/api/books/{book_id}/glossary"
    assert client.post(base, json={"source_term": "  "}).status_code == 400
    bad = client.post(base, json={"source_term": "x", "translations": {"ta": "y"}})
    assert bad.status_code == 400 and "own language" in bad.json()["detail"]
    assert client.put(f"{base}/999", json={"source_term": "x"}).status_code == 400
