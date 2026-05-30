from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from pidgin.util.ids import utc_now_iso


MIGRATION_VERSION = "001_initial"
SYSTEM_EMPLOYEE_ID = "000000000000000000000000"


def migration_sql_path() -> Path:
    return Path(__file__).resolve().parents[3] / "migrations" / f"{MIGRATION_VERSION}.sql"


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_migrations(conn: sqlite3.Connection) -> None:
    sql_path = migration_sql_path()
    sql = sql_path.read_text(encoding="utf-8")
    digest = checksum(sql)

    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()

    if has_table:
        applied = conn.execute(
            "SELECT version FROM schema_migrations WHERE version = ?",
            (MIGRATION_VERSION,),
        ).fetchone()
        if applied is not None:
            return

    conn.executescript(sql)
    conn.execute(
        "INSERT INTO schema_migrations (version, applied_at, checksum) VALUES (?, ?, ?)",
        (MIGRATION_VERSION, utc_now_iso(), digest),
    )
    conn.commit()


def init_workspace_db(conn: sqlite3.Connection, workspace_id: str, display_name: str) -> None:
    now = utc_now_iso()
    existing = conn.execute("SELECT id FROM workspace LIMIT 1").fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO workspace (
              id, display_name, debug_export_enabled, debug_export_retention_days,
              created_at, updated_at
            ) VALUES (?, ?, 0, 7, ?, ?)
            """,
            (workspace_id, display_name, now, now),
        )
        conn.commit()
