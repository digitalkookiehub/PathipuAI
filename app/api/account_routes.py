"""Sign-up (with owner approval), forgotten passwords, and the owner's Accounts page. All paths are under /api."""

import logging
import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.auth_routes import _client_ip
from app.api.deps import check_origin, get_conn, get_settings, require_admin
from app.auth.service import (
    RESET_MINUTES,
    Account,
    AuthError,
    User,
    account_email,
    admin_emails,
    approve_account,
    create_password_reset,
    create_user,
    delete_account,
    disable_account,
    list_accounts,
    reset_password,
    set_admin,
)
from app.auth.throttle import LoginThrottle
from app.config import Settings
from app.services.mailer import send_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth")
admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])
# Sign-ups and reset emails are limited to a few per address (and per email) every ten minutes.
request_limit = LoginThrottle()

FORGOT_ANSWER = (
    "If an account uses that email address, a link to choose a new password has been sent. "
    "Please check your inbox (and the spam folder)."
)


class Registration(BaseModel):
    username: str = Field(max_length=100)
    email: str = Field(max_length=254)
    password: str = Field(max_length=500)


class ForgotRequest(BaseModel):
    email: str = Field(max_length=254)


class ResetRequest(BaseModel):
    token: str = Field(max_length=200)
    new_password: str = Field(max_length=500)


class OwnerChange(BaseModel):
    is_admin: bool


class AccountOut(BaseModel):
    id: int
    username: str
    email: str | None
    is_admin: bool
    status: str
    created_at: str


def _limit(*keys: str) -> None:
    wait = request_limit.seconds_locked(*keys)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Please wait {max(1, round(wait / 60))} minute(s) and try again.",
            headers={"Retry-After": str(wait)},
        )
    request_limit.record_failure(*keys)


def _site(settings: Settings, request: Request) -> str:
    """The address put into emailed links. Behind the proxy it must come from settings, never from the request."""
    if settings.public_url:
        return settings.public_url
    if settings.trust_proxy:
        raise HTTPException(status_code=503, detail="Password reset is not set up on this server yet.")
    return str(request.base_url).rstrip("/")


@router.post("/register", status_code=201)
def register(
    body: Registration,
    request: Request,
    background: BackgroundTasks,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Create an account that can sign in straight away. Owners are told, and can disable it on the Accounts page."""
    check_origin(request)
    _limit(f"register-ip:{_client_ip(request, settings)}")
    try:
        user = create_user(conn, body.username, body.password, email=body.email)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    site = settings.public_url or str(request.base_url).rstrip("/")
    for owner in admin_emails(conn):
        background.add_task(
            send_email,
            settings,
            owner,
            "PathippuAI: a new account was created",
            f"{user.username} ({body.email.strip().lower()}) created an account.\n\n"
            f"If you do not know this person, disable or remove it on the Accounts page: {site}/accounts\n",
        )
    return {"message": "Your account was created. You can sign in now."}


@router.post("/forgot-password", status_code=202)
def forgot_password(
    body: ForgotRequest,
    request: Request,
    background: BackgroundTasks,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Email a one-time link to choose a new password. The answer is the same whether or not the email is known."""
    check_origin(request)
    _limit(f"forgot-ip:{_client_ip(request, settings)}", f"forgot-email:{body.email.strip().lower()}")
    if not settings.mail_enabled:
        raise HTTPException(
            status_code=503,
            detail="Email is not set up on this server, so reset links cannot be sent. Please ask the owner.",
        )
    site = _site(settings, request)
    found = create_password_reset(conn, body.email)
    if found is not None:
        token, username, email = found
        background.add_task(
            send_email,
            settings,
            email,
            "PathippuAI: choose a new password",
            f"Hello {username},\n\n"
            f"Someone (hopefully you) asked to reset your PathippuAI password. Open this link to choose a new one:\n\n"
            f"{site}/reset-password?token={token}\n\n"
            f"The link works once and for {RESET_MINUTES} minutes. If you did not ask for this, ignore this email; "
            "your password stays the same.\n",
        )
    return {"message": FORGOT_ANSWER}


@router.post("/reset-password", status_code=204)
def use_reset_link(body: ResetRequest, request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> None:
    """Choose a new password with the emailed link. Every browser is signed out."""
    check_origin(request)
    try:
        reset_password(conn, body.token, body.new_password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- the owner's Accounts page ----------------------------------------------------------------------------------


def _out(account: Account) -> AccountOut:
    return AccountOut(**account.__dict__)


def _run(action) -> AccountOut:  # noqa: ANN001
    try:
        return _out(action())
    except AuthError as exc:
        status = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@admin_router.get("/users", response_model=list[AccountOut])
def accounts(conn: sqlite3.Connection = Depends(get_conn)) -> list[AccountOut]:
    """Every account; ones waiting for approval come first."""
    return [_out(a) for a in list_accounts(conn)]


@admin_router.post("/users/{user_id}/approve", response_model=AccountOut)
def approve(
    user_id: int,
    request: Request,
    background: BackgroundTasks,
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> AccountOut:
    """Let an account sign in (and tell the person by email when email is set up)."""
    result = _run(lambda: approve_account(conn, user_id))
    email = account_email(conn, user_id)
    if email:
        site = settings.public_url or str(request.base_url).rstrip("/")
        background.add_task(
            send_email,
            settings,
            email,
            "PathippuAI: your account is approved",
            f"Hello {result.username},\n\nYour PathippuAI account was approved. You can sign in now: {site}\n",
        )
    return result


@admin_router.post("/users/{user_id}/disable", response_model=AccountOut)
def disable(
    user_id: int, conn: sqlite3.Connection = Depends(get_conn), owner: User = Depends(require_admin)
) -> AccountOut:
    """Stop an account from signing in; it is signed out at once."""
    return _run(lambda: disable_account(conn, user_id, owner))


@admin_router.post("/users/{user_id}/owner", response_model=AccountOut)
def change_owner(
    user_id: int, body: OwnerChange, conn: sqlite3.Connection = Depends(get_conn), owner: User = Depends(require_admin)
) -> AccountOut:
    """Give or take away owner rights (managing accounts)."""
    return _run(lambda: set_admin(conn, user_id, body.is_admin, owner))


@admin_router.delete("/users/{user_id}", status_code=204)
def remove(user_id: int, conn: sqlite3.Connection = Depends(get_conn), owner: User = Depends(require_admin)) -> None:
    """Remove an account, for example a sign-up you do not recognise. Books are not affected."""
    try:
        delete_account(conn, user_id, owner)
    except AuthError as exc:
        status = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
