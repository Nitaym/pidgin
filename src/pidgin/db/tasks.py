from __future__ import annotations

import sqlite3
from typing import Any

from pidgin.util.ids import new_ulid, utc_now_iso

_OPEN_STATUSES = ("open", "in_progress", "blocked")


def create_task(
    conn: sqlite3.Connection,
    *,
    owner_principal_id: str,
    title: str,
    description: str | None = None,
    due_at: str | None = None,
    source_turn_id: str | None = None,
) -> str:
    task_id = new_ulid()
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO tasks (
          id, title, description, owner_principal_id, source_turn_id,
          current_status, due_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)
        """,
        (task_id, title, description, owner_principal_id, source_turn_id, due_at, now, now),
    )
    conn.execute(
        """
        INSERT INTO tasks_status_log (
          id, task_id, from_status, to_status, actor_principal_id, reason, occurred_at
        ) VALUES (?, ?, NULL, 'open', ?, ?, ?)
        """,
        (new_ulid(), task_id, owner_principal_id, "Opened", now),
    )
    conn.commit()
    return task_id


def set_task_status(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    owner_principal_id: str,
    to_status: str,
    outcome: str | None = None,
) -> bool:
    row = conn.execute(
        "SELECT current_status FROM tasks WHERE id = ? AND owner_principal_id = ?",
        (task_id, owner_principal_id),
    ).fetchone()
    if row is None:
        return False
    from_status = row["current_status"]
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE tasks SET current_status = ?, outcome = COALESCE(?, outcome), updated_at = ?
        WHERE id = ?
        """,
        (to_status, outcome, now, task_id),
    )
    conn.execute(
        """
        INSERT INTO tasks_status_log (
          id, task_id, from_status, to_status, actor_principal_id, reason, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (new_ulid(), task_id, from_status, to_status, owner_principal_id, outcome, now),
    )
    conn.commit()
    return True


def list_open_tasks(
    conn: sqlite3.Connection, *, owner_principal_id: str, limit: int = 25
) -> list[dict[str, Any]]:
    placeholders = ", ".join("?" for _ in _OPEN_STATUSES)
    rows = conn.execute(
        f"""
        SELECT id, title, current_status, due_at, created_at FROM tasks
        WHERE owner_principal_id = ? AND current_status IN ({placeholders})
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (owner_principal_id, *_OPEN_STATUSES, limit),
    ).fetchall()
    return [dict(row) for row in rows]
