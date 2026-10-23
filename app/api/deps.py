"""FastAPI dependencies: settings, a database connection per request, and book lookup."""

import hmac
import sqlite3
from collections.abc import Iterator
from functools import lru_cache
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request

from app.auth.service import User, get_session
from app.config import Settings, load_settings
from app.db import connect
from app.services.books import get_book


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process."""
    return load_settings()


def get_conn(settings: Settings = Depends(get_settings)) -> Iterator[sqlite3.Connection]:
    """Open a migrated SQLite connection for one request and close it afterwards."""
    conn = connect(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


def require_book(book_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> sqlite3.Row:
    """Return the book from the URL or answer 404."""
    book = get_book(conn, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="That book was not found.")
    return book


SESSION_COOKIE = "pathippu_session"
CSRF_COOKIE = "pathippu_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def check_origin(request: Request) -> None:
    """Refuse requests that were sent from a page on another website (the Origin must match this site)."""
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host", ""):
        raise HTTPException(status_code=403, detail="This request came from another site and was refused.")


def require_user(
    request: Request, conn: sqlite3.Connection = Depends(get_conn), settings: Settings = Depends(get_settings)
) -> User:
    """The signed-in user, or 401. Changes (POST/PUT/DELETE) also need the CSRF token and a same-site origin."""
    if not settings.auth_required:
        return User(id=0, username="local")
    session = get_session(conn, request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    if request.method not in SAFE_METHODS:
        check_origin(request)
        if not hmac.compare_digest(request.headers.get(CSRF_HEADER, ""), session.csrf_token):
            raise HTTPException(status_code=403, detail="This page has expired. Please reload it and try again.")
    return session.user
