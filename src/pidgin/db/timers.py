from __future__ import annotations

import sqlite3
from typing import Any

from pidgin.util.ids import new_ulid, utc_now_iso


def create_timer(
    conn: sqlite3.Connection,
    *,
    ai_employee_id: str,
    scheduled_at: str,
    reason: str,
    originating_turn_id: str,
    inherited_trust_label: str,
) -> str:
    timer_id = new_ulid()
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO agent_timers (
          id, ai_employee_id, scheduled_at, reason, originating_turn_id,
          inherited_trust_label, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            timer_id,
            ai_employee_id,
            scheduled_at,
            reason,
            originating_turn_id,
            inherited_trust_label,
            now,
            now,
        ),
    )
    conn.commit()
    return timer_id


def find_pending_timer_near(
    conn: sqlite3.Connection,
    *,
    ai_employee_id: str,
    originating_turn_id: str,
    scheduled_at: str,
    window_seconds: float = 20.0,
) -> dict[str, Any] | None:
    """Find a pending timer from the same turn firing at ~the same time.

    Models sometimes re-issue a schedule_self call they already made (the
    transcript between invocations doesn't preserve tool calls), producing
    near-identical duplicates seconds apart. Distinct follow-ups in one turn
    have meaningfully different fire times, so a tight window only catches
    the re-issued ones.
    """
    from datetime import datetime

    target = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
    rows = conn.execute(
        """
        SELECT * FROM agent_timers
        WHERE ai_employee_id = ? AND originating_turn_id = ? AND status = 'pending'
        """,
        (ai_employee_id, originating_turn_id),
    ).fetchall()
    for row in rows:
        existing = datetime.fromisoformat(row["scheduled_at"].replace("Z", "+00:00"))
        if abs((existing - target).total_seconds()) <= window_seconds:
            return dict(row)
    return None


def list_due_timers(conn: sqlite3.Connection, *, limit: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM agent_timers
        WHERE status = 'pending' AND scheduled_at <= ?
        ORDER BY scheduled_at ASC
        LIMIT ?
        """,
        (utc_now_iso(), limit),
    ).fetchall()
    return [dict(row) for row in rows]


def mark_timer_fired(
    conn: sqlite3.Connection,
    timer_id: str,
    *,
    fired_event_id: str,
) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE agent_timers
        SET status = 'fired', fired_at = ?, fired_event_id = ?, updated_at = ?
        WHERE id = ? AND status = 'pending'
        """,
        (now, fired_event_id, now, timer_id),
    )
    conn.commit()
