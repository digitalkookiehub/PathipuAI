"""SQLite connection helper and simple versioned migrations."""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(database_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with foreign keys on and migrations applied."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may open and close a request's connection on different worker threads. Each connection
    # belongs to a single request (or job) and is never shared concurrently, so this is safe.
    conn = sqlite3.connect(database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply any unapplied migrations in filename order; return the names applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.commit()
    applied = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
    newly_applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in applied:
            continue
        script = path.read_text(encoding="utf-8")
        try:
            conn.executescript(
                f"BEGIN;\n{script}\nINSERT INTO schema_migrations (name) VALUES ('{path.name}');\nCOMMIT;"
            )
        except sqlite3.Error:
            conn.rollback()
            logger.exception("Migration %s failed", path.name)
            raise
        newly_applied.append(path.name)
        logger.info("Applied migration %s", path.name)
    return newly_applied
