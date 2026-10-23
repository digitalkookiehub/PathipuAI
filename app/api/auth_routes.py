"""Public routes: health checks, sign in and out, first-time setup, password change. All paths are under /api."""

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    check_origin,
    get_conn,
    get_settings,
    require_user,
)
from app.auth.service import (
    AuthError,
    User,
    authenticate,
    change_password,
    create_session,
    create_user,
    end_session,
    get_session,
    user_count,
)
from app.auth.throttle import LoginThrottle
from app.config import Settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
throttle = LoginThrottle()
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


class Credentials(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=500)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=500)
    new_password: str = Field(max_length=500)


def _client_ip(request: Request, settings: Settings) -> str:
    """The caller's address; behind our own reverse proxy (TRUST_PROXY) it comes from X-Forwarded-For."""
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _set_cookies(response: Response, settings: Settings, token: str, csrf: str) -> None:
    options = {
        "max_age": settings.session_hours * 3600,
        "secure": settings.cookie_secure,
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **options)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **options)  # the page reads this one and echoes it back


def _start(response: Response, conn: sqlite3.Connection, settings: Settings, user: User) -> None:
    token, csrf = create_session(conn, user, settings.session_hours)
    _set_cookies(response, settings, token, csrf)


@router.get("/health")
def health() -> dict[str, str]:
    """Simple liveness check (does not touch the database)."""
    return {"status": "ok"}


@router.get("/health/ready")
def ready(conn: sqlite3.Connection = Depends(get_conn), settings: Settings = Depends(get_settings)) -> dict[str, str]:
    """Readiness check for Docker and monitoring: the database answers and the data folder is writable."""
    try:
        conn.execute("SELECT 1").fetchone()
        probe = settings.data_dir / ".health"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
    except (sqlite3.Error, OSError) as exc:
        logger.error("Readiness check failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Not ready.") from exc
    return {"status": "ready"}


@router.get("/auth/status")
def status(
    request: Request, conn: sqlite3.Connection = Depends(get_conn), settings: Settings = Depends(get_settings)
) -> dict[str, object]:
    """Whether sign-in is needed, whether this browser is signed in, and whether the first account must be created."""
    if not settings.auth_required:
        return {"auth_required": False, "authenticated": True, "username": "local", "setup_required": False}
    session = get_session(conn, request.cookies.get(SESSION_COOKIE))
    return {
        "auth_required": True,
        "authenticated": session is not None,
        "username": session.user.username if session else None,
        "setup_required": user_count(conn) == 0,
    }


@router.post("/auth/setup")
def setup(
    body: Credentials,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Create the first account. Only possible while there are no accounts, and only from the same computer."""
    check_origin(request)
    if user_count(conn) > 0:
        raise HTTPException(status_code=409, detail="An account already exists. Please sign in.")
    direct = (request.client.host if request.client else "") in LOCAL_HOSTS
    proxied = any(h in request.headers for h in ("x-forwarded-for", "forwarded", "x-real-ip"))
    if not direct or proxied:
        raise HTTPException(
            status_code=403,
            detail="The first account can only be created on the server itself. "
            "Run: docker compose exec app python -m scripts.create_user",
        )
    try:
        user = create_user(conn, body.username, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _start(response, conn, settings, user)
    return {"username": user.username}


@router.post("/auth/login")
def login(
    body: Credentials,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Sign in. Five wrong passwords lock the username and the address for ten minutes."""
    check_origin(request)
    keys = (f"user:{body.username.strip().lower()}", f"ip:{_client_ip(request, settings)}")
    wait = throttle.seconds_locked(*keys)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Too many wrong passwords. Please wait {max(1, round(wait / 60))} minute(s) and try again.",
            headers={"Retry-After": str(wait)},
        )
    user = authenticate(conn, body.username, body.password)
    if user is None:
        throttle.record_failure(*keys)
        logger.warning("Failed sign-in from %s", keys[1])
        raise HTTPException(status_code=401, detail="The username or password is not right.")
    throttle.reset(*keys)
    _start(response, conn, settings, user)
    return {"username": user.username}


@router.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_conn),
    _user: User = Depends(require_user),
) -> None:
    """Sign out; this browser's session stops working immediately."""
    end_session(conn, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.post("/auth/change-password", status_code=204)
def change(
    body: PasswordChange,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_user),
) -> None:
    """Change the password. Other signed-in browsers are signed out."""
    try:
        change_password(conn, user, body.current_password, body.new_password, request.cookies.get(SESSION_COOKIE))
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
