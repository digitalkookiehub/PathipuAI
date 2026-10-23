"""Safe on-disk storage layout. Paths use generated IDs, never user filenames."""

import re
import uuid
from pathlib import Path

BOOK_SUBDIRS = ("pages", "ocr", "corrected", "translations", "exports")
_UUID_RE = re.compile(r"^[0-9a-f]{32}$")


class UnsafePathError(ValueError):
    """Raised when a path would escape the data directory."""


def new_book_uuid() -> str:
    """Generate an internal identifier used as the book's storage folder name."""
    return uuid.uuid4().hex


def book_dir(data_dir: Path, book_uuid: str) -> Path:
    """Return the book's folder, validating the ID and keeping it inside data_dir."""
    if not _UUID_RE.fullmatch(book_uuid):
        raise UnsafePathError("Invalid book identifier.")
    root = (data_dir / "books").resolve()
    path = (root / book_uuid).resolve()
    if path.parent != root:
        raise UnsafePathError("Path escapes the data directory.")
    return path


def safe_join(base: Path, *parts: str) -> Path:
    """Join parts under base, rejecting anything that resolves outside base."""
    base = base.resolve()
    path = base.joinpath(*parts).resolve()
    if base != path and base not in path.parents:
        raise UnsafePathError("Path escapes the allowed directory.")
    return path


def create_book_dirs(data_dir: Path, book_uuid: str) -> Path:
    """Create the book's folder structure with owner-only permissions."""
    root = book_dir(data_dir, book_uuid)
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name in BOOK_SUBDIRS:
        (root / name).mkdir(mode=0o700)
    return root
