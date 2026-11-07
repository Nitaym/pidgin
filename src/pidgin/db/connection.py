from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from pidgin.util.ids import utc_now_iso

MIGRATION_VERSIONS = (
    "001_initial",
    "002_hire_customization",
    "003_remove_rooms",
    "004_slack_messaging",
    "005_autonomy",
    "006_execution_grants",
    "007_change_gated_wakeup",
    "008_token_usage_index",
    "009_devwork",
    "010_dev_terminals",
)
SYSTEM_EMPLOYEE_ID = "000000000000000000000000"


def migrations_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "migrations"


def migration_sql_path(version: str) -> Path:
    return migrations_dir() / f"{version}.sql"


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # The background worker and request handlers each hold their own connection
    # to the same file; wait on a writer's lock instead of failing immediately.
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def apply_migrations(conn: sqlite3.Connection) -> None:
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()

    for version in MIGRATION_VERSIONS:
        sql_path = migration_sql_path(version)
        sql = sql_path.read_text(encoding="utf-8")
        digest = checksum(sql)

        if has_table:
            applied = conn.execute(
                "SELECT version FROM schema_migrations WHERE version = ?",
                (version,),
            ).fetchone()
            if applied is not None:
                continue

        if version == "003_remove_rooms" and not _table_exists(conn, "rooms"):
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at, checksum) VALUES (?, ?, ?)",
                (version, utc_now_iso(), digest),
            )
            has_table = True
            continue

        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at, checksum) VALUES (?, ?, ?)",
            (version, utc_now_iso(), digest),
        )
        has_table = True

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
