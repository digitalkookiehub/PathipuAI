import dataclasses
import io
import sqlite3
import tarfile
import threading
from datetime import datetime, timedelta

import pytest

from app.auth.service import authenticate
from app.db import connect
from app.services import books as books_service
from app.services.books import create_book
from scripts import backup, create_user

PASSWORD = "correct horse battery"


@pytest.fixture
def book_id(conn, settings, make_pdf):
    return create_book(
        conn,
        settings,
        title="நூல்",
        author="குரு",
        description="",
        source_language="ta",
        publication_details="",
        pdf_bytes=make_pdf(2),
    )


def archive_names(path):
    with tarfile.open(path) as tar:
        return tar.getnames()


def new_settings(settings, tmp_path, name):
    root = tmp_path / name
    return dataclasses.replace(settings, data_dir=root / "data", database_path=root / "data" / "pathippuai.db")


# --- backup and restore -----------------------------------------------------------------------------------------


def test_backup_holds_the_database_and_the_originals_but_not_exports(conn, settings, book_id, tmp_path):
    exports = next((settings.data_dir / "books").iterdir()) / "exports"
    (exports / "source-1.pdf").write_bytes(b"%PDF export")
    archive = backup.create_backup(settings, tmp_path / "bk")
    names = archive_names(archive)
    assert "database.sqlite3" in names and any(n.endswith("original.pdf") for n in names)
    assert not any("exports/source-1.pdf" in n for n in names)
    with_exports = backup.create_backup(
        settings, tmp_path / "bk", include_exports=True, now=datetime.now() + timedelta(seconds=5)
    )
    assert any("exports/source-1.pdf" in n for n in archive_names(with_exports))


def test_backup_is_a_consistent_snapshot_while_the_app_writes(conn, settings, book_id, tmp_path):
    stop = threading.Event()

    def writer():
        db = connect(settings.database_path)
        n = 0
        while not stop.is_set():
            with db:
                db.execute("INSERT INTO text_history (entity_type, entity_id, action) VALUES ('page', 1, ?)", (str(n),))
            n += 1
        db.close()

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        archive = backup.create_backup(settings, tmp_path / "bk")
    finally:
        stop.set()
        thread.join()
    with tarfile.open(archive) as tar:
        data = tar.extractfile("database.sqlite3").read()
    snapshot = tmp_path / "snap.db"
    snapshot.write_bytes(data)
    assert sqlite3.connect(snapshot).execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_restore_brings_back_the_book_and_its_files(conn, settings, book_id, tmp_path):
    archive = backup.create_backup(settings, tmp_path / "bk")
    fresh = new_settings(settings, tmp_path, "server2")
    backup.restore_backup(fresh, archive)
    restored = connect(fresh.database_path)
    book = books_service.get_book(restored, book_id)
    assert book["title"] == "நூல்" and book["page_count"] == 2
    original = fresh.data_dir / "books" / book["uuid"] / "original.pdf"
    assert original.read_bytes().startswith(b"%PDF")
    assert restored.execute("SELECT COUNT(*) FROM book_pages").fetchone()[0] == 2


def test_restore_never_overwrites_data_by_accident(conn, settings, book_id, tmp_path):
    archive = backup.create_backup(settings, tmp_path / "bk")
    with pytest.raises(backup.BackupError, match="already data here"):
        backup.restore_backup(settings, archive)
    conn.close()
    books_service_dir = settings.data_dir / "books"
    (books_service_dir / "marker.txt").write_text("keep a copy", encoding="utf-8")
    backup.restore_backup(settings, archive, force=True)
    assert settings.database_path.with_suffix(".before-restore").exists()  # the old database is kept aside
    assert (settings.data_dir / "books.before-restore" / "marker.txt").exists()


def test_restore_rejects_archives_that_try_to_escape(settings, tmp_path):
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 3
        tar.addfile(info, io.BytesIO(b"bad"))
    fresh = new_settings(settings, tmp_path, "server3")
    with pytest.raises(backup.BackupError, match="unexpected paths"):
        backup.restore_backup(fresh, evil)
    assert not (tmp_path / "server3" / "escape.txt").exists() and not (tmp_path / "escape.txt").exists()
    with pytest.raises(backup.BackupError, match="not found"):
        backup.restore_backup(fresh, tmp_path / "missing.tar.gz")
    garbage = tmp_path / "garbage.tar.gz"
    garbage.write_bytes(b"not a tar file")
    with pytest.raises(backup.BackupError, match="could not be read"):
        backup.restore_backup(fresh, garbage)


def test_old_backups_are_removed_beyond_the_limit(conn, settings, book_id, tmp_path):
    start = datetime(2026, 1, 1, 12, 0, 0)
    for day in range(5):
        backup.create_backup(settings, tmp_path / "bk", keep=3, now=start + timedelta(days=day))
    names = [p.name for p in backup.list_backups(tmp_path / "bk")]
    assert len(names) == 3 and names[0].startswith("pathippuai-backup-20260103")


def test_command_line_backup_and_restore(conn, settings, book_id, tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "load_settings", lambda: settings)
    assert backup.main(["create", "--dest", str(tmp_path / "cli"), "--keep", "2"]) == 0
    assert len(backup.list_backups(tmp_path / "cli")) == 1
    assert backup.main(["list", "--dest", str(tmp_path / "cli")]) == 0
    archive = backup.list_backups(tmp_path / "cli")[0]
    assert backup.main(["restore", str(archive)]) == 1  # refuses: data exists
    conn.close()  # the app is stopped before a restore (Windows cannot replace an open database)
    assert backup.main(["restore", str(archive), "--force"]) == 0


# --- the account tool -------------------------------------------------------------------------------------------


def test_create_user_tool_asks_for_the_password_and_checks_it(conn, settings, monkeypatch):
    monkeypatch.setattr(create_user, "load_settings", lambda: settings)
    answers = iter([PASSWORD, PASSWORD])
    assert create_user.main(["guru"], ask=lambda prompt: next(answers)) == 0
    assert authenticate(conn, "guru", PASSWORD) is not None

    mismatch = iter([PASSWORD, "something else entirely"])
    assert create_user.main(["second"], ask=lambda prompt: next(mismatch)) == 1
    weak = iter(["short", "short"])
    assert create_user.main(["third"], ask=lambda prompt: next(weak)) == 1
    duplicate = iter([PASSWORD, PASSWORD])
    assert create_user.main(["guru"], ask=lambda prompt: next(duplicate)) == 1
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_create_user_tool_can_reset_a_password(conn, settings, monkeypatch):
    monkeypatch.setattr(create_user, "load_settings", lambda: settings)
    first = iter([PASSWORD, PASSWORD])
    create_user.main(["guru"], ask=lambda prompt: next(first))
    new = "an even better passphrase"
    reset = iter([new, new])
    assert create_user.main(["guru", "--reset"], ask=lambda prompt: next(reset)) == 0
    assert authenticate(conn, "guru", new) is not None and authenticate(conn, "guru", PASSWORD) is None
    missing = iter([new, new])
    assert create_user.main(["ghost", "--reset"], ask=lambda prompt: next(missing)) == 1
