"""DB access for the developer worker: worker config, runs, run events."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pidgin.util.ids import new_ulid, utc_now_iso

ACTIVE_STATUSES = ("queued", "claiming", "preparing", "running")
FINAL_STATUSES = ("done", "handed_off", "ended_open", "failed", "timed_out", "cancelled", "dropped")

DEFAULT_RULES: dict[str, Any] = {
    "assigned": True,  # rule 1: assigned to the worker in Todo
    "agent_ready": True,  # rule 2: unassigned agent-ready in Todo, when nothing assigned waits
    "agent_ready_label": "agent-ready",
    "skip_labels": ["owner-only", "runner-failed"],
    "failed_label": "runner-failed",
}

DEFAULT_STATUS_MAP: dict[str, str] = {
    "todo": "Todo",
    "in_progress": "In Progress",
    "needs_owner": "Needs owner",
    "done": "Done",
    "triage": "Triage",
}

DEFAULT_ALLOWED_TOOLS = ", ".join(
    [
        "Read",
        "Edit",
        "Write",
        "Glob",
        "Grep",
        "TodoWrite",
        "WebFetch",
        "Bash(git status:*)",
        "Bash(git diff:*)",
        "Bash(git log:*)",
        "Bash(git add:*)",
        "Bash(git commit:*)",
        "Bash(git show:*)",
        "Bash(git branch:*)",
        "Bash(git rev-parse:*)",
        "Bash(npm:*)",
        "Bash(npx:*)",
        "Bash(node:*)",
        "Bash(ls:*)",
        "Bash(cat:*)",
        "Bash(rg:*)",
        "Bash(grep:*)",
        "Bash(python:*)",
        "Bash(uv:*)",
        "Bash(pytest:*)",
    ]
)


CONFIG_FIELDS = (
    "enabled",
    "linear_installation_id",
    "team_id",
    "team_key",
    "owner_linear_id",
    "owner_linear_name",
    "repo_path",
    "base_branch",
    "worktree_root",
    "setup_command",
    "branch_pattern",
    "max_concurrent",
    "time_limit_min",
    "idle_limit_min",
    "max_turns",
    "poll_seconds",
    "model",
    "permission_mode",
    "allowed_tools",
)


def default_worktree_root(handle: str) -> str:
    return str(Path.home() / ".pidgin" / "worktrees" / handle)


def get_worker(conn: sqlite3.Connection, ai_employee_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM dev_workers WHERE ai_employee_id = ?", (ai_employee_id,)
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["rules"] = {**DEFAULT_RULES, **json.loads(data.pop("rules_json") or "{}")}
    data["status_map"] = {**DEFAULT_STATUS_MAP, **json.loads(data.pop("status_map_json") or "{}")}
    data["queue"] = json.loads(data.pop("queue_json") or "[]")
    if not data.get("allowed_tools"):
        data["allowed_tools"] = DEFAULT_ALLOWED_TOOLS
    return data


def ensure_worker(conn: sqlite3.Connection, ai_employee_id: str, handle: str) -> dict[str, Any]:
    existing = get_worker(conn, ai_employee_id)
    if existing is not None:
        return existing
    now = utc_now_iso()
    conn.execute(
        """INSERT INTO dev_workers (ai_employee_id, worktree_root, allowed_tools, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (ai_employee_id, default_worktree_root(handle), DEFAULT_ALLOWED_TOOLS, now, now),
    )
    conn.commit()
    worker = get_worker(conn, ai_employee_id)
    assert worker is not None
    return worker


def update_worker(conn: sqlite3.Connection, ai_employee_id: str, updates: dict[str, Any]) -> None:
    sets: list[str] = []
    params: list[Any] = []
    for key, value in updates.items():
        if key in CONFIG_FIELDS or key in (
            "viewer_id",
            "viewer_name",
            "last_poll_at",
            "last_poll_ok_at",
            "last_poll_error",
        ):
            sets.append(f"{key} = ?")
            params.append(value)
        elif key == "rules":
            sets.append("rules_json = ?")
            params.append(json.dumps(value))
        elif key == "status_map":
            sets.append("status_map_json = ?")
            params.append(json.dumps(value))
        elif key == "queue":
            sets.append("queue_json = ?")
            params.append(json.dumps(value))
    if not sets:
        return
    sets.append("updated_at = ?")
    params.append(utc_now_iso())
    params.append(ai_employee_id)
    conn.execute(f"UPDATE dev_workers SET {', '.join(sets)} WHERE ai_employee_id = ?", params)
    conn.commit()


def list_enabled_workers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT w.ai_employee_id FROM dev_workers w
           JOIN ai_employees e ON e.id = w.ai_employee_id
           WHERE w.enabled = 1 AND e.current_status != 'offboarded'"""
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        worker = get_worker(conn, row["ai_employee_id"])
        if worker is not None:
            out.append(worker)
    return out


# -- runs ----------------------------------------------------------------------


def create_run(
    conn: sqlite3.Connection,
    *,
    ai_employee_id: str,
    ticket_id: str,
    ticket_key: str,
    ticket_title: str,
    ticket_url: str,
    trigger_class: str,
) -> str | None:
    """Insert a queued run. Returns None if the ticket already has an active run."""
    attempt_row = conn.execute(
        "SELECT COUNT(*) AS n FROM code_runs WHERE ticket_id = ? AND status != 'dropped'",
        (ticket_id,),
    ).fetchone()
    run_id = new_ulid()
    try:
        conn.execute(
            """INSERT INTO code_runs (id, ai_employee_id, ticket_id, ticket_key, ticket_title,
                 ticket_url, trigger_class, attempt, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)""",
            (
                run_id,
                ai_employee_id,
                ticket_id,
                ticket_key,
                ticket_title,
                ticket_url,
                trigger_class,
                int(attempt_row["n"]) + 1,
                utc_now_iso(),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        return None
    return run_id


def get_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM code_runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def update_run(conn: sqlite3.Connection, run_id: str, **fields: Any) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE code_runs SET {sets} WHERE id = ?", [*fields.values(), run_id])
    conn.commit()


def active_runs(
    conn: sqlite3.Connection, ai_employee_id: str | None = None
) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    query = f"SELECT * FROM code_runs WHERE status IN ({placeholders})"
    params: list[Any] = list(ACTIVE_STATUSES)
    if ai_employee_id:
        query += " AND ai_employee_id = ?"
        params.append(ai_employee_id)
    return [dict(r) for r in conn.execute(query + " ORDER BY created_at", params).fetchall()]


def runs_for_agent(
    conn: sqlite3.Connection, ai_employee_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM code_runs WHERE ai_employee_id = ? ORDER BY created_at DESC LIMIT ?",
        (ai_employee_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def last_run_for_ticket(conn: sqlite3.Connection, ticket_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM code_runs WHERE ticket_id = ? AND status != 'dropped' "
        "ORDER BY created_at DESC LIMIT 1",
        (ticket_id,),
    ).fetchone()
    return dict(row) if row else None


def runs_for_ticket(conn: sqlite3.Connection, ticket_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM code_runs WHERE ticket_id = ? AND status != 'dropped' ORDER BY created_at",
        (ticket_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_event(
    conn: sqlite3.Connection,
    run_id: str,
    kind: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO code_run_events (id, run_id, kind, message, data_json, occurred_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (new_ulid(), run_id, kind, message, json.dumps(data) if data else None, utc_now_iso()),
    )
    conn.commit()


def run_events(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM code_run_events WHERE run_id = ? ORDER BY occurred_at, id", (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]
