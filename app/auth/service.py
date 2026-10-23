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
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
RESET_MINUTES = 30


class AuthError(BookError):
    """A sign-in or account problem; the message is safe to show."""


@dataclass(frozen=True)
class User:
    """A signed-in person."""

    id: int
    username: str
    is_admin: bool = False


@dataclass(frozen=True)
class Account:
    """An account as the owner sees it on the Accounts page."""

    id: int
    username: str
    email: str | None
    is_admin: bool
    status: str  # "pending" (waiting for approval), "active" or "disabled"
    created_at: str


class AccountPendingError(AuthError):
    """The password is right but the owner has not approved the account yet."""


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


def normalize_email(email: str) -> str:
    """A lower-case, trimmed email address, or AuthError if it does not look like one."""
    email = email.strip().lower()
    if len(email) > 254 or not EMAIL_RE.fullmatch(email):
        raise AuthError("Please enter a valid email address.")
    return email


def create_user(
    conn: sqlite3.Connection,
    username: str,
    password: str,
    *,
    email: str | None = None,
    is_admin: bool = False,
    pending: bool = False,
) -> User:
    """Create an account. The username is 3-64 letters, digits or . _ @ -; the password follows the password rules.

    A pending account cannot sign in until the owner approves it.
    """
    username = username.strip()
    if not USERNAME_RE.fullmatch(username):
        raise AuthError("The username must be 3-64 characters: letters, digits and . _ @ -")
    email = normalize_email(email) if email else None
    try:
        validate_password(password, username)
    except WeakPasswordError as exc:
        raise AuthError(str(exc)) from exc
    if conn.execute("SELECT 1 FROM users WHERE lower(username) = lower(?)", (username,)).fetchone():
        raise AuthError("That username is already taken.")
    if email and conn.execute("SELECT 1 FROM users WHERE lower(email) = ?", (email,)).fetchone():
        raise AuthError("An account with that email address already exists.")
    with conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, email, is_admin, pending, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (username, hash_password(password), email, int(is_admin), int(pending), int(not pending)),
        )
    logger.info("Created user id=%s pending=%s", cur.lastrowid, pending)
    return User(id=int(cur.lastrowid), username=username, is_admin=is_admin)


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> User | None:
    """The user if the username and password are right and the account is active, otherwise None."""
    row = conn.execute(
        "SELECT id, username, password_hash, is_active, is_admin, pending FROM users WHERE lower(username) = lower(?)",
        (username.strip(),),
    ).fetchone()
    valid = verify_password(password, row["password_hash"] if row else None)
    if row is None or not valid:
        return None
    if row["pending"]:
        raise AccountPendingError("Your account is waiting for the owner's approval.")
    if not row["is_active"]:
        return None
    return User(id=row["id"], username=row["username"], is_admin=bool(row["is_admin"]))


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
        "SELECT s.csrf_token, s.expires_at, u.id, u.username, u.is_active, u.is_admin FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
        (_hash_token(token),),
    ).fetchone()
    if row is None or not row["is_active"] or row["expires_at"] < _now().isoformat():
        return None
    return Session(user=User(row["id"], row["username"], bool(row["is_admin"])), csrf_token=row["csrf_token"])


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


# --- password reset ---------------------------------------------------------------------------------------------


def create_password_reset(conn: sqlite3.Connection, email: str) -> tuple[str, str, str] | None:
    """(token, username, email) for a one-time reset link, if an active account has this email; otherwise None.

    Older unused links for the same account stop working.
    """
    try:
        email = normalize_email(email)
    except AuthError:
        return None
    row = conn.execute(
        "SELECT id, username FROM users WHERE lower(email) = ? AND is_active = 1 AND pending = 0", (email,)
    ).fetchone()
    if row is None:
        return None
    token = secrets.token_urlsafe(32)
    expires = (_now() + timedelta(minutes=RESET_MINUTES)).isoformat()
    with conn:
        conn.execute("DELETE FROM password_resets WHERE user_id = ? OR expires_at < ?", (row["id"], _now().isoformat()))
        conn.execute(
            "INSERT INTO password_resets (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (_hash_token(token), row["id"], expires),
        )
    logger.info("Password reset requested for user id=%s", row["id"])
    return token, row["username"], email


def reset_password(conn: sqlite3.Connection, token: str, new: str) -> None:
    """Use a reset link: set the new password, end the link and sign the account out everywhere."""
    expired = AuthError("This reset link has expired or was already used. Please ask for a new one.")
    if not token or len(token) > 200:
        raise expired
    row = conn.execute(
        "SELECT r.expires_at, r.used_at, u.id AS user_id, u.username, u.is_active FROM password_resets r "
        "JOIN users u ON u.id = r.user_id WHERE r.token_hash = ?",
        (_hash_token(token),),
    ).fetchone()
    if row is None or row["used_at"] or row["expires_at"] < _now().isoformat() or not row["is_active"]:
        raise expired
    try:
        validate_password(new, row["username"])
    except WeakPasswordError as exc:
        raise AuthError(str(exc)) from exc
    with conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE id = ?",
            (hash_password(new), row["user_id"]),
        )
        conn.execute("DELETE FROM password_resets WHERE user_id = ?", (row["user_id"],))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
    logger.info("Password reset completed for user id=%s", row["user_id"])


# --- the owner's Accounts page ----------------------------------------------------------------------------------


def _status(row: sqlite3.Row) -> str:
    if row["pending"]:
        return "pending"
    return "active" if row["is_active"] else "disabled"


def list_accounts(conn: sqlite3.Connection) -> list[Account]:
    """Every account, waiting-for-approval ones first."""
    rows = conn.execute(
        "SELECT id, username, email, is_admin, is_active, pending, created_at FROM users "
        "ORDER BY pending DESC, lower(username)"
    ).fetchall()
    return [Account(r["id"], r["username"], r["email"], bool(r["is_admin"]), _status(r), r["created_at"]) for r in rows]


def get_account(conn: sqlite3.Connection, user_id: int) -> Account:
    """One account, or AuthError if there is none with this id."""
    for account in list_accounts(conn):
        if account.id == user_id:
            return account
    raise AuthError("That account was not found.")


def _active_admins(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1 AND is_active = 1 AND pending = 0").fetchone()[0]
    )


def _guard_last_owner(conn: sqlite3.Connection, target: Account) -> None:
    if target.is_admin and target.status == "active" and _active_admins(conn) <= 1:
        raise AuthError("This is the only owner account. Make someone else an owner first.")


def approve_account(conn: sqlite3.Connection, user_id: int) -> Account:
    """Let a waiting (or disabled) account sign in."""
    get_account(conn, user_id)
    with conn:
        conn.execute(
            "UPDATE users SET pending = 0, is_active = 1, updated_at = datetime('now') WHERE id = ?", (user_id,)
        )
    logger.info("Approved user id=%s", user_id)
    return get_account(conn, user_id)


def disable_account(conn: sqlite3.Connection, user_id: int, acting: User) -> Account:
    """Stop an account from signing in and end its sessions. You cannot disable yourself or the last owner."""
    target = get_account(conn, user_id)
    if target.id == acting.id:
        raise AuthError("You cannot disable your own account.")
    _guard_last_owner(conn, target)
    with conn:
        conn.execute(
            "UPDATE users SET pending = 0, is_active = 0, updated_at = datetime('now') WHERE id = ?", (user_id,)
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    logger.info("Disabled user id=%s", user_id)
    return get_account(conn, user_id)


def delete_account(conn: sqlite3.Connection, user_id: int, acting: User) -> None:
    """Remove an account (for example a sign-up you do not want). Books stay; they are shared."""
    target = get_account(conn, user_id)
    if target.id == acting.id:
        raise AuthError("You cannot remove your own account.")
    _guard_last_owner(conn, target)
    with conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    logger.info("Removed user id=%s", user_id)


def set_admin(conn: sqlite3.Connection, user_id: int, is_admin: bool, acting: User) -> Account:
    """Make an account an owner (can manage accounts) or a normal user."""
    target = get_account(conn, user_id)
    if not is_admin:
        if target.id == acting.id:
            raise AuthError("You cannot remove your own owner rights.")
        _guard_last_owner(conn, target)
    with conn:
        conn.execute(
            "UPDATE users SET is_admin = ?, updated_at = datetime('now') WHERE id = ?", (int(is_admin), user_id)
        )
    return get_account(conn, user_id)


def admin_emails(conn: sqlite3.Connection) -> list[str]:
    """Email addresses of active owners (to tell them about new sign-ups)."""
    rows = conn.execute(
        "SELECT email FROM users WHERE is_admin = 1 AND is_active = 1 AND pending = 0 AND email IS NOT NULL"
    ).fetchall()
    return [r["email"] for r in rows]


def account_email(conn: sqlite3.Connection, user_id: int) -> str | None:
    """The email address of one account, if it has one."""
    row = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["email"] if row else None
