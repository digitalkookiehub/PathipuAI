"""Password hashing and rules. Passwords are never stored or logged in plain text."""

import base64
import hashlib

import bcrypt

MIN_LENGTH = 10
MAX_LENGTH = 200
# bcrypt only looks at the first 72 bytes, so the password is reduced to a fixed-size digest first.
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt(rounds=12))


class WeakPasswordError(ValueError):
    """The password does not meet the rules; the message is safe to show the author."""


def _prepare(password: str) -> bytes:
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def validate_password(password: str, username: str = "") -> None:
    """Raise WeakPasswordError unless the password is long enough and not trivially guessable."""
    if len(password) < MIN_LENGTH:
        raise WeakPasswordError(f"Please use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        raise WeakPasswordError("That password is too long.")
    lowered = password.lower()
    if username and lowered == username.lower():
        raise WeakPasswordError("The password must not be the same as the username.")
    if len(set(password)) < 4:
        raise WeakPasswordError("Please use a less repetitive password.")
    if lowered in {"password123", "1234567890", "qwertyuiop", "pathippuai", "pathippuai123"}:
        raise WeakPasswordError("That password is too easy to guess.")


def hash_password(password: str) -> str:
    """A salted bcrypt hash of the password."""
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    """Check a password. Takes the same time whether or not the user exists (pass None for an unknown user)."""
    if password_hash is None:
        bcrypt.checkpw(_prepare(password), _DUMMY_HASH)
        return False
    try:
        return bcrypt.checkpw(_prepare(password), password_hash.encode("ascii"))
    except ValueError:
        return False
