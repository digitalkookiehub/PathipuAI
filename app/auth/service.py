"""Users and login sessions."""

import hashlib
import logging
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.auth.passwords import WeakPasswordError, hash_password, validate_password, verify_password
from app.services.books import BookError

logger = logging.getLogger(__name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9._@-]{3,64}$")


class AuthError(BookError):
    """A sign-in or account problem; the message is safe to show."""


@dataclass(frozen=True)
class User:
    """A signed-in person."""

    id: int
    username: str


@dataclass(frozen=True)
class Session:
    """A valid login session."""

    user: User
    csrf_token: str


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def user_count(conn: sqlite3.Connection) -> int:
    """How many accounts exist."""
    return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])


def create_user(conn: sqlite3.Connection, username: str, password: str) -> User:
    """Create an account. The username is 3-64 letters, digits or . _ @ -; the password follows the password rules."""
    username = username.strip()
    if not USERNAME_RE.fullmatch(username):
        raise AuthError("The username must be 3-64 characters: letters, digits and . _ @ -")
    try:
        validate_password(password, username)
    except WeakPasswordError as exc:
        raise AuthError(str(exc)) from exc
    if conn.execute("SELECT 1 FROM users WHERE lower(username) = lower(?)", (username,)).fetchone():
        raise AuthError("That username is already taken.")
    with conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, hash_password(password))
        )
    logger.info("Created user id=%s", cur.lastrowid)
    return User(id=int(cur.lastrowid), username=username)


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> User | None:
    """The user if the username and password are right and the account is active, otherwise None."""
    row = conn.execute(
        "SELECT id, username, password_hash, is_active FROM users WHERE lower(username) = lower(?)",
        (username.strip(),),
    ).fetchone()
    valid = verify_password(password, row["password_hash"] if row else None)
    if row is None or not valid or not row["is_active"]:
        return None
    return User(id=row["id"], username=row["username"])


def create_session(conn: sqlite3.Connection, user: User, hours: int) -> tuple[str, str]:
    """Start a session; returns (session token for the cookie, CSRF token). Expired sessions are cleaned up."""
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    expires = (_now() + timedelta(hours=hours)).isoformat()
    with conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now().isoformat(),))
        conn.execute(
            "INSERT INTO sessions (token_hash, csrf_token, user_id, expires_at) VALUES (?, ?, ?, ?)",
            (_hash_token(token), csrf, user.id, expires),
        )
    return token, csrf


def get_session(conn: sqlite3.Connection, token: str | None) -> Session | None:
    """The session for a cookie value, or None if it is missing, unknown, expired or the account is disabled."""
    if not token:
        return None
    row = conn.execute(
        "SELECT s.csrf_token, s.expires_at, u.id, u.username, u.is_active FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
        (_hash_token(token),),
    ).fetchone()
    if row is None or not row["is_active"] or row["expires_at"] < _now().isoformat():
        return None
    return Session(user=User(row["id"], row["username"]), csrf_token=row["csrf_token"])


def end_session(conn: sqlite3.Connection, token: str | None) -> None:
    """Sign out: the session stops working immediately."""
    if token:
        with conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))


def change_password(
    conn: sqlite3.Connection, user: User, current: str, new: str, keep_token: str | None = None
) -> None:
    """Change the password (the current one is required) and sign out every other session."""
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()
    if row is None or not verify_password(current, row["password_hash"]):
        raise AuthError("The current password is not right.")
    try:
        validate_password(new, user.username)
    except WeakPasswordError as exc:
        raise AuthError(str(exc)) from exc
    with conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE id = ?",
            (hash_password(new), user.id),
        )
        if keep_token:
            conn.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user.id, _hash_token(keep_token))
            )
        else:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user.id,))


def set_password(conn: sqlite3.Connection, username: str, new: str) -> None:
    """Set a new password for an existing user (used by the command-line tool) and sign them out everywhere."""
    row = conn.execute("SELECT id FROM users WHERE lower(username) = lower(?)", (username.strip(),)).fetchone()
    if row is None:
        raise AuthError("There is no such user.")
    try:
        validate_password(new, username)
    except WeakPasswordError as exc:
        raise AuthError(str(exc)) from exc
    with conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE id = ?",
            (hash_password(new), row["id"]),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
