import dataclasses
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.api import auth_routes
from app.api.deps import get_settings
from app.api.main import FRONTEND_DIST, create_app
from app.auth import passwords
from app.auth.service import AuthError, authenticate, create_session, create_user, get_session, set_password
from app.auth.throttle import LoginThrottle

PASSWORD = "correct horse battery"
NEW_PASSWORD = "another long passphrase"
OWNER = {"username": "guru", "password": PASSWORD}


@pytest.fixture
def secure_settings(settings):
    return dataclasses.replace(settings, auth_required=True)


@pytest.fixture(autouse=True)
def fresh_throttle(monkeypatch):
    monkeypatch.setattr(auth_routes, "throttle", LoginThrottle())


def make_client(settings, host="127.0.0.1"):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, client=(host, 50000))


@pytest.fixture
def client(secure_settings):
    return make_client(secure_settings)


@pytest.fixture
def owner(client):
    """A client that has created the first account and then signed out again."""
    assert client.post("/api/auth/setup", json=OWNER).status_code == 200
    client.post("/api/auth/logout", headers=csrf(client))
    return client


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("pathippu_csrf") or ""}


def sign_in(client, password=PASSWORD, username="guru"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


# --- passwords --------------------------------------------------------------------------------------------------


def test_passwords_are_hashed_salted_and_checked():
    first, second = passwords.hash_password(PASSWORD), passwords.hash_password(PASSWORD)
    assert first != second and PASSWORD not in first and first.startswith("$2")
    assert passwords.verify_password(PASSWORD, first) and not passwords.verify_password("wrong password!", first)
    assert not passwords.verify_password(PASSWORD, None) and not passwords.verify_password(PASSWORD, "garbage")


def test_long_passwords_are_not_silently_truncated():
    base = "x" * 80
    stored = passwords.hash_password(base + "A")
    assert passwords.verify_password(base + "A", stored) and not passwords.verify_password(base + "B", stored)


@pytest.mark.parametrize("weak", ["short", "aaaaaaaaaaaa", "password123", "abababababab"])
def test_weak_passwords_are_refused(weak):
    with pytest.raises(passwords.WeakPasswordError):
        passwords.validate_password(weak, "guru")


def test_password_must_differ_from_the_username():
    with pytest.raises(passwords.WeakPasswordError, match="username"):
        passwords.validate_password("guru-the-great", "Guru-The-Great")


# --- accounts in the database -----------------------------------------------------------------------------------


def test_accounts_store_only_a_hash_and_usernames_are_unique(conn):
    create_user(conn, "Guru", PASSWORD)
    assert conn.execute("SELECT password_hash FROM users").fetchone()[0] != PASSWORD
    with pytest.raises(AuthError, match="already taken"):
        create_user(conn, "guru", PASSWORD)
    for bad in ("ab", "has space", "x" * 65, "semi;colon"):
        with pytest.raises(AuthError, match="username"):
            create_user(conn, bad, PASSWORD)
    assert authenticate(conn, "GURU", PASSWORD).username == "Guru"
    assert authenticate(conn, "guru", "wrong") is None and authenticate(conn, "nobody", PASSWORD) is None
    conn.execute("UPDATE users SET is_active = 0")
    conn.commit()
    assert authenticate(conn, "guru", PASSWORD) is None


def test_set_password_signs_everyone_out(conn):
    user = create_user(conn, "guru", PASSWORD)
    token, _ = create_session(conn, user, 12)
    assert get_session(conn, token) is not None
    set_password(conn, "guru", NEW_PASSWORD)
    assert get_session(conn, token) is None
    assert authenticate(conn, "guru", NEW_PASSWORD) is not None and authenticate(conn, "guru", PASSWORD) is None
    with pytest.raises(AuthError, match="no such user"):
        set_password(conn, "ghost", NEW_PASSWORD)


# --- the HTTP API -----------------------------------------------------------------------------------------------


def test_everything_except_health_and_sign_in_needs_a_login(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/health/ready").json() == {"status": "ready"}
    for path in ("/api/books", "/api/languages", "/api/books/1", "/api/translation/provider", "/api/books/1/exports"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/books/1/ocr", json={}).status_code == 401
    assert client.delete("/api/books/1?confirm=true").status_code == 401
    status = client.get("/api/auth/status").json()
    assert status == {"auth_required": True, "authenticated": False, "username": None, "setup_required": True}


def test_login_can_be_switched_off_for_local_use(settings):
    open_client = make_client(dataclasses.replace(settings, auth_required=False))
    assert open_client.get("/api/books").status_code == 200
    assert open_client.get("/api/auth/status").json()["authenticated"] is True


def test_first_account_is_created_only_on_the_server_itself(secure_settings):
    remote = make_client(secure_settings, host="203.0.113.9")
    refused = remote.post("/api/auth/setup", json=OWNER)
    assert refused.status_code == 403 and "scripts.create_user" in refused.json()["detail"]
    local = make_client(secure_settings)
    proxied = local.post("/api/auth/setup", json=OWNER, headers={"X-Forwarded-For": "203.0.113.9"})
    assert proxied.status_code == 403  # a request relayed by a reverse proxy is not "on the server itself"
    assert local.post("/api/auth/setup", json={"username": "guru", "password": "short"}).status_code == 400
    created = local.post("/api/auth/setup", json=OWNER)
    assert created.status_code == 200 and local.get("/api/books").status_code == 200  # signed in straight away
    assert local.get("/api/auth/status").json()["username"] == "guru"
    assert make_client(secure_settings).post("/api/auth/setup", json=OWNER).status_code == 409  # only once


def test_wrong_passwords_get_one_vague_answer(owner):
    unknown = sign_in(owner, username="nobody")
    wrong = sign_in(owner, password="not the password")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json() == {"detail": "The username or password is not right."}


def test_repeated_failures_lock_the_account_for_a_while(owner):
    for _ in range(5):
        assert sign_in(owner, password="not the password").status_code == 401
    locked = sign_in(owner)  # even the right password is refused while locked
    assert locked.status_code == 429 and "Too many wrong passwords" in locked.json()["detail"]
    assert int(locked.headers["retry-after"]) > 0
    assert sign_in(owner, username="someone-else").status_code == 429  # the address is locked too


def test_throttle_expires_and_resets():
    now = [0.0]
    throttle = LoginThrottle(clock=lambda: now[0])
    for _ in range(5):
        throttle.record_failure("user:a")
    assert throttle.seconds_locked("user:a") > 0 and throttle.seconds_locked("user:b") == 0
    now[0] += 11 * 60
    assert throttle.seconds_locked("user:a") == 0
    for _ in range(4):
        throttle.record_failure("user:a")
    throttle.reset("user:a")
    throttle.record_failure("user:a")
    assert throttle.seconds_locked("user:a") == 0


def test_signed_in_session_works_and_cookies_are_safe(owner, secure_settings):
    response = sign_in(owner)
    assert response.status_code == 200 and response.json() == {"username": "guru"}
    cookies = {c.split("=")[0]: c.lower() for c in response.headers.get_list("set-cookie")}
    assert "httponly" in cookies["pathippu_session"] and "samesite=lax" in cookies["pathippu_session"]
    assert "httponly" not in cookies["pathippu_csrf"]  # the page must be able to read this one
    assert owner.get("/api/books").status_code == 200
    token = owner.cookies.get("pathippu_session")
    stored = sqlite3.connect(secure_settings.database_path).execute("SELECT token_hash FROM sessions").fetchall()
    assert token not in str(stored)  # only a hash of the session token is stored


def test_secure_cookies_when_served_over_https(secure_settings):
    https = make_client(dataclasses.replace(secure_settings, cookie_secure=True))
    response = https.post("/api/auth/setup", json=OWNER)
    assert all("secure" in c.lower() for c in response.headers.get_list("set-cookie"))


def test_changes_need_the_csrf_token_and_a_same_site_origin(owner):
    sign_in(owner)
    body = {"title": "t", "source_language": "ta"}
    files = {"file": ("a.pdf", b"x", "application/pdf")}
    assert owner.post("/api/books", data=body, files=files).status_code == 403  # no token: refused
    assert owner.post("/api/books", data=body, files=files, headers={"X-CSRF-Token": "forged"}).status_code == 403
    cross_site = {**csrf(owner), "Origin": "https://evil.example"}
    refused = owner.post("/api/books", data=body, files=files, headers=cross_site)
    assert refused.status_code == 403 and "another site" in refused.json()["detail"]
    # with the right token the request gets past the security checks (the fake PDF is then rejected by validation)
    assert owner.post("/api/books", data=body, files=files, headers=csrf(owner)).status_code == 400
    same_site = {**csrf(owner), "Origin": "http://testserver"}
    assert owner.post("/api/books", data=body, files=files, headers=same_site).status_code == 400
    assert (
        owner.get("/api/books", headers={"Origin": "https://evil.example"}).status_code == 200
    )  # reads change nothing


def test_login_also_refuses_other_sites(owner):
    response = owner.post("/api/auth/login", json=OWNER, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_sign_out_ends_the_session_immediately(owner):
    sign_in(owner)
    old_cookie = owner.cookies.get("pathippu_session")
    assert owner.post("/api/auth/logout").status_code == 403  # sign-out is a change: it needs the token too
    assert owner.post("/api/auth/logout", headers=csrf(owner)).status_code == 204
    assert owner.get("/api/books").status_code == 401
    owner.cookies.set("pathippu_session", old_cookie)  # replaying the old cookie does not work either
    assert owner.get("/api/books").status_code == 401


def test_sessions_expire_and_disabled_accounts_are_locked_out(owner, secure_settings):
    sign_in(owner)
    db = sqlite3.connect(secure_settings.database_path)
    db.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
    db.commit()
    assert owner.get("/api/books").status_code == 401
    sign_in(owner)
    assert owner.get("/api/books").status_code == 200
    db.execute("UPDATE users SET is_active = 0")
    db.commit()
    assert owner.get("/api/books").status_code == 401


def test_changing_the_password(owner, secure_settings):
    sign_in(owner)
    other_browser = make_client(secure_settings)
    sign_in(other_browser)
    assert other_browser.get("/api/books").status_code == 200
    url = "/api/auth/change-password"
    wrong = owner.post(url, json={"current_password": "nope", "new_password": NEW_PASSWORD}, headers=csrf(owner))
    assert wrong.status_code == 400 and "current password" in wrong.json()["detail"]
    weak = owner.post(url, json={"current_password": PASSWORD, "new_password": "short"}, headers=csrf(owner))
    assert weak.status_code == 400
    good = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    assert owner.post(url, json=good, headers=csrf(owner)).status_code == 204
    assert owner.get("/api/books").status_code == 200  # this browser stays signed in
    assert other_browser.get("/api/books").status_code == 401  # every other one is signed out
    owner.post("/api/auth/logout", headers=csrf(owner))
    assert sign_in(owner).status_code == 401 and sign_in(owner, password=NEW_PASSWORD).status_code == 200


def test_security_headers_and_hidden_api_docs(client):
    api = client.get("/api/health")
    assert api.headers["x-content-type-options"] == "nosniff" and api.headers["x-frame-options"] == "DENY"
    assert api.headers["referrer-policy"] == "same-origin" and "content-security-policy" not in api.headers
    assert client.get("/api/docs").status_code == 404 and client.get("/api/openapi.json").status_code == 404
    if FRONTEND_DIST.is_dir():
        csp = client.get("/").headers["content-security-policy"]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "script-src 'self'" in csp
        assert "unsafe-eval" not in csp
