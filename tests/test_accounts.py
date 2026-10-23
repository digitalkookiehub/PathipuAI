"""Sign-up with owner approval, password reset by email, and the owner's Accounts page."""

import dataclasses
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.api import account_routes, auth_routes
from app.api.deps import get_settings
from app.api.main import create_app
from app.auth.service import create_user
from app.auth.throttle import LoginThrottle
from app.db import connect

PASSWORD = "correct horse battery"
NEW_PASSWORD = "another long passphrase"


@pytest.fixture
def sent(monkeypatch):
    """Capture emails instead of sending them."""
    outbox: list[dict[str, str]] = []

    def fake_send(_settings, to, subject, body):
        outbox.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr(account_routes, "send_email", fake_send)
    return outbox


@pytest.fixture(autouse=True)
def fresh_limits(monkeypatch):
    monkeypatch.setattr(auth_routes, "throttle", LoginThrottle())
    monkeypatch.setattr(account_routes, "request_limit", LoginThrottle())


@pytest.fixture
def site_settings(settings):
    return dataclasses.replace(
        settings,
        auth_required=True,
        smtp_host="smtp.example.test",
        smtp_from="books@example.test",
        public_url="https://books.example.test",
    )


def make_client(settings):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("pathippu_csrf") or ""}


@pytest.fixture
def owner(site_settings):
    db = connect(site_settings.database_path)
    create_user(db, "guru@example.test", PASSWORD, email="guru@example.test", is_admin=True)
    db.close()
    client = make_client(site_settings)
    assert (
        client.post("/api/auth/login", json={"username": "guru@example.test", "password": PASSWORD}).status_code == 200
    )
    return client


def register(client, username="helper", email="helper@example.test", password=PASSWORD):
    return client.post("/api/auth/register", json={"username": username, "email": email, "password": password})


def sign_in(client, username="helper", password=PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def user_id(settings, username):
    db = sqlite3.connect(settings.database_path)
    return db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()[0]


def reset_link(mail):
    match = re.search(r"https://books\.example\.test/reset-password\?token=(\S+)", mail["body"])
    assert match, mail["body"]
    return match.group(1)


# --- sign-up ----------------------------------------------------------------------------------------------------


def test_sign_up_works_at_once_and_tells_the_owner(owner, site_settings, sent):
    visitor = make_client(site_settings)
    answer = register(visitor)
    assert answer.status_code == 201 and "sign in now" in answer.json()["message"]
    assert [m["to"] for m in sent] == ["guru@example.test"]
    assert "helper" in sent[0]["body"] and "https://books.example.test/accounts" in sent[0]["body"]
    assert sign_in(visitor, password="not the password").status_code == 401
    assert sign_in(visitor).status_code == 200 and visitor.get("/api/books").status_code == 200
    assert visitor.get("/api/auth/status").json()["is_admin"] is False
    status = {a["username"]: a["status"] for a in owner.get("/api/admin/users").json()}
    assert status["helper"] == "active"


def test_accounts_left_waiting_by_older_versions_can_sign_in(owner, site_settings):
    """Migration 008 switches on accounts that an older version left waiting for approval."""
    from app.db import migrate

    db = connect(site_settings.database_path)
    create_user(db, "waiting", PASSWORD, email="waiting@example.test", pending=True)
    db.execute("DELETE FROM schema_migrations WHERE name = '008_no_approval.sql'")
    db.commit()
    assert db.execute("SELECT is_active FROM users WHERE username = 'waiting'").fetchone()[0] == 0
    assert "008_no_approval.sql" in migrate(db)
    db.close()
    assert sign_in(make_client(site_settings), "waiting").status_code == 200


def test_sign_up_checks_the_details(owner, site_settings, sent):
    visitor = make_client(site_settings)
    assert register(visitor, email="not-an-email").status_code == 400
    assert register(visitor, password="short").status_code == 400
    assert register(visitor, username="a b").status_code == 400
    taken = register(visitor, username="guru@example.test", email="other@example.test")
    assert taken.status_code == 400 and "already taken" in taken.json()["detail"]
    dup = register(visitor, username="someone", email="GURU@example.test")
    assert dup.status_code == 400 and "email address already exists" in dup.json()["detail"]
    cross = visitor.post(
        "/api/auth/register",
        json={"username": "x-user", "email": "x@example.test", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert cross.status_code == 403


def test_sign_ups_are_rate_limited(owner, site_settings, sent):
    visitor = make_client(site_settings)
    for n in range(5):
        register(visitor, username=f"user{n}", email=f"user{n}@example.test")
    limited = register(visitor, username="user9", email="user9@example.test")
    assert limited.status_code == 429


# --- forgot password --------------------------------------------------------------------------------------------


def test_forgot_password_emails_a_one_time_link(owner, site_settings, sent):
    visitor = make_client(site_settings)
    answer = visitor.post("/api/auth/forgot-password", json={"email": "Guru@Example.test "})
    assert answer.status_code == 202
    assert len(sent) == 1 and sent[0]["to"] == "guru@example.test"
    token = reset_link(sent[0])
    assert token not in str(
        sqlite3.connect(site_settings.database_path).execute("SELECT * FROM password_resets").fetchall()
    )

    weak = visitor.post("/api/auth/reset-password", json={"token": token, "new_password": "short"})
    assert weak.status_code == 400
    assert (
        visitor.post("/api/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}).status_code == 204
    )
    assert owner.get("/api/books").status_code == 401  # every browser is signed out
    again = visitor.post("/api/auth/reset-password", json={"token": token, "new_password": "yet another passphrase"})
    assert again.status_code == 400 and "expired or was already used" in again.json()["detail"]
    assert sign_in(visitor, "guru@example.test", PASSWORD).status_code == 401
    assert sign_in(visitor, "guru@example.test", NEW_PASSWORD).status_code == 200


def test_forgot_password_does_not_reveal_who_has_an_account(owner, site_settings, sent):
    visitor = make_client(site_settings)
    known = visitor.post("/api/auth/forgot-password", json={"email": "guru@example.test"})
    unknown = visitor.post("/api/auth/forgot-password", json={"email": "nobody@example.test"})
    garbage = visitor.post("/api/auth/forgot-password", json={"email": "garbage"})
    assert known.status_code == unknown.status_code == garbage.status_code == 202
    assert known.json() == unknown.json() == garbage.json()
    assert len(sent) == 1


def test_disabled_accounts_get_no_reset_link(owner, site_settings, sent):
    visitor = make_client(site_settings)
    register(visitor)
    owner.post(f"/api/admin/users/{user_id(site_settings, 'helper')}/disable", headers=csrf(owner))
    sent.clear()
    visitor.post("/api/auth/forgot-password", json={"email": "helper@example.test"})
    assert sent == []


def test_only_the_newest_link_works_and_links_expire(owner, site_settings, sent):
    visitor = make_client(site_settings)
    visitor.post("/api/auth/forgot-password", json={"email": "guru@example.test"})
    visitor.post("/api/auth/forgot-password", json={"email": "guru@example.test"})
    first, second = reset_link(sent[0]), reset_link(sent[1])
    assert (
        visitor.post("/api/auth/reset-password", json={"token": first, "new_password": NEW_PASSWORD}).status_code == 400
    )
    db = sqlite3.connect(site_settings.database_path)
    db.execute("UPDATE password_resets SET expires_at = '2000-01-01T00:00:00+00:00'")
    db.commit()
    assert (
        visitor.post("/api/auth/reset-password", json={"token": second, "new_password": NEW_PASSWORD}).status_code
        == 400
    )
    bogus = visitor.post("/api/auth/reset-password", json={"token": "made-up", "new_password": NEW_PASSWORD})
    assert bogus.status_code == 400


def test_reset_requests_are_rate_limited(owner, site_settings, sent):
    visitor = make_client(site_settings)
    for _ in range(5):
        visitor.post("/api/auth/forgot-password", json={"email": "guru@example.test"})
    assert visitor.post("/api/auth/forgot-password", json={"email": "guru@example.test"}).status_code == 429


def test_reset_needs_email_to_be_set_up(settings, sent):
    plain = make_client(dataclasses.replace(settings, auth_required=True))
    answer = plain.post("/api/auth/forgot-password", json={"email": "guru@example.test"})
    assert answer.status_code == 503 and "ask the owner" in answer.json()["detail"]
    assert plain.get("/api/auth/status").json()["reset_available"] is False


def test_links_never_use_the_address_a_visitor_sends(site_settings, sent):
    behind_proxy = dataclasses.replace(site_settings, public_url="", trust_proxy=True)
    db = connect(behind_proxy.database_path)
    create_user(db, "guru", PASSWORD, email="guru@example.test", is_admin=True)
    db.close()
    client = make_client(behind_proxy)
    answer = client.post(
        "/api/auth/forgot-password", json={"email": "guru@example.test"}, headers={"Host": "evil.example"}
    )
    assert answer.status_code == 503 and sent == []


# --- the owner's Accounts page ----------------------------------------------------------------------------------


def test_only_owners_can_manage_accounts(owner, site_settings, sent):
    visitor = make_client(site_settings)
    register(visitor)
    helper = user_id(site_settings, "helper")
    owner.post(f"/api/admin/users/{helper}/approve", headers=csrf(owner))
    sign_in(visitor)
    assert visitor.get("/api/admin/users").status_code == 403
    assert (
        visitor.post(f"/api/admin/users/{helper}/owner", json={"is_admin": True}, headers=csrf(visitor)).status_code
        == 403
    )
    assert make_client(site_settings).get("/api/admin/users").status_code == 401
    listing = owner.get("/api/admin/users").json()
    assert {a["username"]: a["status"] for a in listing} == {"guru@example.test": "active", "helper": "active"}
    assert all("password" not in str(a).lower() for a in listing)


def test_disable_enable_promote_and_remove(owner, site_settings, sent):
    visitor = make_client(site_settings)
    register(visitor)
    helper = user_id(site_settings, "helper")
    owner.post(f"/api/admin/users/{helper}/approve", headers=csrf(owner))
    sign_in(visitor)
    disabled = owner.post(f"/api/admin/users/{helper}/disable", headers=csrf(owner))
    assert disabled.json()["status"] == "disabled" and visitor.get("/api/books").status_code == 401
    assert sign_in(visitor).status_code == 401
    owner.post(f"/api/admin/users/{helper}/approve", headers=csrf(owner))
    promoted = owner.post(f"/api/admin/users/{helper}/owner", json={"is_admin": True}, headers=csrf(owner))
    assert promoted.json()["is_admin"] is True
    sign_in(visitor)
    assert visitor.get("/api/admin/users").status_code == 200
    assert owner.delete(f"/api/admin/users/{helper}", headers=csrf(owner)).status_code == 204
    assert visitor.get("/api/books").status_code == 401
    assert owner.delete(f"/api/admin/users/{helper}", headers=csrf(owner)).status_code == 404


def test_the_owner_cannot_lock_themselves_out(owner, site_settings):
    me = user_id(site_settings, "guru@example.test")
    for answer in (
        owner.post(f"/api/admin/users/{me}/disable", headers=csrf(owner)),
        owner.delete(f"/api/admin/users/{me}", headers=csrf(owner)),
        owner.post(f"/api/admin/users/{me}/owner", json={"is_admin": False}, headers=csrf(owner)),
    ):
        assert answer.status_code == 400
    assert owner.get("/api/admin/users").status_code == 200


def test_account_changes_need_the_csrf_token(owner, site_settings):
    me = user_id(site_settings, "guru@example.test")
    assert owner.post(f"/api/admin/users/{me}/approve").status_code == 403


# --- upgrading an existing database -----------------------------------------------------------------------------


def test_existing_first_account_becomes_the_owner(tmp_path):
    """A database from before sign-up existed: its first account becomes the owner, email usernames become emails."""
    from app.db import MIGRATIONS_DIR, migrate

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT)")
    for script in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if script.name >= "007":
            break
        old.executescript(script.read_text(encoding="utf-8"))
        old.execute("INSERT INTO schema_migrations (name) VALUES (?)", (script.name,))
    old.execute("INSERT INTO users (username, password_hash) VALUES ('muralidrn09@gmail.com', 'x')")
    old.execute("INSERT INTO users (username, password_hash) VALUES ('second', 'x')")
    old.commit()
    old.row_factory = sqlite3.Row
    assert "007_accounts.sql" in migrate(old)
    rows = old.execute("SELECT username, email, is_admin, pending, is_active FROM users ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [
        ("muralidrn09@gmail.com", "muralidrn09@gmail.com", 1, 0, 1),
        ("second", None, 0, 0, 1),
    ]
