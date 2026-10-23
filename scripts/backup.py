"""Back up and restore PathippuAI's data: the database and every book's files (original PDF, page images, text).

    python -m scripts.backup create [--dest DIR] [--keep 14] [--include-exports]
    python -m scripts.backup list [--dest DIR]
    python -m scripts.backup restore ARCHIVE [--force]

A backup is one .tar.gz holding a consistent snapshot of the database (taken with SQLite's backup API, so it is safe
while the app runs) and the books folder. Keep copies somewhere other than the server. Stop the app before restoring.
"""

import argparse
import logging
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from app.config import Settings, load_settings

logger = logging.getLogger(__name__)

DATABASE_MEMBER = "database.sqlite3"
BOOKS_MEMBER = "books"
PREFIX = "pathippuai-backup-"


class BackupError(Exception):
    """A backup or restore problem; the message says what to do."""


def default_destination(settings: Settings) -> Path:
    """Where backups go unless told otherwise: a folder next to the data folder (not inside the books)."""
    return settings.data_dir.parent / "backups"


def create_backup(
    settings: Settings,
    destination: Path | None = None,
    *,
    keep: int = 14,
    include_exports: bool = False,
    now: datetime | None = None,
) -> Path:
    """Write a timestamped backup archive and remove the oldest ones beyond `keep`; returns the archive path."""
    destination = destination or default_destination(settings)
    destination.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    archive = destination / f"{PREFIX}{stamp}.tar.gz"
    if archive.exists():
        raise BackupError(f"{archive.name} already exists. Wait a second and try again.")
    with tempfile.TemporaryDirectory() as scratch:
        snapshot = Path(scratch) / DATABASE_MEMBER
        if settings.database_path.exists():
            source = sqlite3.connect(settings.database_path)
            target = sqlite3.connect(snapshot)
            try:
                source.backup(target)  # a consistent copy even while the app is writing
            finally:
                target.close()
                source.close()
        books = settings.data_dir / BOOKS_MEMBER
        with tarfile.open(archive, "w:gz") as tar:
            if snapshot.exists():
                tar.add(snapshot, arcname=DATABASE_MEMBER)
            if books.is_dir():
                tar.add(books, arcname=BOOKS_MEMBER, filter=lambda info: _filter(info, include_exports))
    try:
        os.chmod(archive, 0o600)  # backups hold private manuscripts
    except OSError:
        logger.warning("Could not restrict permissions on %s", archive.name)
    _prune(destination, keep)
    logger.info("Created backup %s", archive.name)
    return archive


def _filter(info: tarfile.TarInfo, include_exports: bool) -> tarfile.TarInfo | None:
    parts = Path(info.name).parts
    if not include_exports and "exports" in parts[2:3]:
        return None  # exported PDFs can be made again
    return info


def list_backups(destination: Path) -> list[Path]:
    """Backup archives in a folder, oldest first."""
    return sorted(destination.glob(f"{PREFIX}*.tar.gz"))


def _prune(destination: Path, keep: int) -> None:
    backups = list_backups(destination)
    for old in backups[: max(0, len(backups) - max(1, keep))]:
        old.unlink(missing_ok=True)


def _safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = []
    for member in tar.getmembers():
        path = Path(member.name)
        if path.is_absolute() or ".." in path.parts or path.parts[0] not in (DATABASE_MEMBER, BOOKS_MEMBER):
            raise BackupError("This file is not a PathippuAI backup (it contains unexpected paths).")
        if not (member.isfile() or member.isdir()):
            raise BackupError("This file is not a PathippuAI backup (it contains links or special files).")
        members.append(member)
    return members


def restore_backup(settings: Settings, archive: Path, *, force: bool = False) -> None:
    """Put a backup back. Refuses to overwrite existing data unless force=True; the old database is kept aside."""
    if not archive.is_file():
        raise BackupError("That backup file was not found.")
    books = settings.data_dir / BOOKS_MEMBER
    has_data = settings.database_path.exists() or (books.is_dir() and any(books.iterdir()))
    if has_data and not force:
        raise BackupError("There is already data here. Stop the app, then run again with --force to replace it.")
    settings.data_dir.parent.mkdir(parents=True, exist_ok=True)  # a brand-new server has no folders yet
    try:
        with tarfile.open(archive, "r:gz") as tar, tempfile.TemporaryDirectory(dir=settings.data_dir.parent) as scratch:
            members = _safe_members(tar)
            # Members were checked above; newer Pythons add their own "data" filter on top of that.
            extra = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            tar.extractall(scratch, members=members, **extra)
            extracted = Path(scratch)
            if not (extracted / DATABASE_MEMBER).is_file():
                raise BackupError("This backup has no database in it.")
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            if settings.database_path.exists():
                aside = settings.database_path.with_suffix(".before-restore")
                shutil.move(str(settings.database_path), aside)
            for leftover in ("-wal", "-shm"):
                Path(str(settings.database_path) + leftover).unlink(missing_ok=True)
            shutil.move(str(extracted / DATABASE_MEMBER), settings.database_path)
            if books.exists():
                shutil.move(str(books), str(books) + ".before-restore")
            if (extracted / BOOKS_MEMBER).is_dir():
                shutil.move(str(extracted / BOOKS_MEMBER), books)
            else:
                books.mkdir(parents=True)
    except tarfile.TarError as exc:
        raise BackupError("That file could not be read as a backup.") from exc
    logger.info("Restored backup %s", archive.name)


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point; returns the exit code."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Back up and restore PathippuAI data.")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="make a backup now")
    create.add_argument("--dest", type=Path, help="folder for backups (default: ../backups next to the data folder)")
    create.add_argument("--keep", type=int, default=14, help="how many backups to keep (default 14)")
    create.add_argument("--include-exports", action="store_true", help="also include exported PDFs")
    listing = commands.add_parser("list", help="show existing backups")
    listing.add_argument("--dest", type=Path)
    restore = commands.add_parser("restore", help="put a backup back (stop the app first)")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--force", action="store_true", help="replace existing data (the old database is kept aside)")
    args = parser.parse_args(argv)
    settings = load_settings()
    try:
        if args.command == "create":
            archive = create_backup(settings, args.dest, keep=args.keep, include_exports=args.include_exports)
            sys.stdout.write(f"Backup created: {archive}\n")
        elif args.command == "list":
            for path in list_backups(args.dest or default_destination(settings)):
                sys.stdout.write(f"{path.name}  {path.stat().st_size / 1024 / 1024:.1f} MB\n")
        else:
            restore_backup(settings, args.archive, force=args.force)
            sys.stdout.write("Restored. Start the app again.\n")
    except BackupError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
