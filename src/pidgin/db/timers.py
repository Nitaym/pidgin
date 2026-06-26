from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from pidgin.util.ids import new_ulid, utc_now_iso

# --- Recurrence (RRULE-lite, see AUTONOMY_SPEC §5) ---------------------------
#
# Three shapes only. at_local_time is interpreted as UTC for MVP
# (AUTONOMY_SPEC open decision 2). Anything richer is deferred to real cron.
#   {"kind": "daily",    "at_local_time": "09:00"}
#   {"kind": "weekly",   "weekday": "mon", "at_local_time": "08:30"}
#   {"kind": "interval", "every_minutes": 240}

_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_hhmm(value: str) -> tuple[int, int]:
    hh, _, mm = value.partition(":")
    return int(hh), int(mm)


def next_occurrence(recurrence: dict[str, Any], *, after: datetime) -> datetime:
    """Next fire time strictly after `after` for an RRULE-lite recurrence."""
    kind = recurrence.get("kind")
    if kind == "interval":
        minutes = float(recurrence.get("every_minutes") or 0)
        if minutes <= 0:
            raise ValueError("interval recurrence needs positive every_minutes")
        return after + timedelta(minutes=minutes)

    hour, minute = _parse_hhmm(str(recurrence.get("at_local_time") or "09:00"))
    if kind == "daily":
        candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= after:
            candidate += timedelta(days=1)
        return candidate
    if kind == "weekly":
        target = _WEEKDAYS.get(str(recurrence.get("weekday") or "mon").lower())
        if target is None:
            raise ValueError(f"unknown weekday: {recurrence.get('weekday')}")
        candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (target - candidate.weekday()) % 7
        candidate += timedelta(days=days_ahead)
        if candidate <= after:
            candidate += timedelta(days=7)
        return candidate
    raise ValueError(f"unknown recurrence kind: {kind!r}")


# --- Timer rows --------------------------------------------------------------


def create_timer(
    conn: sqlite3.Connection,
    *,
    ai_employee_id: str,
    scheduled_at: str,
    reason: str,
    inherited_trust_label: str,
    originating_turn_id: str | None = None,
    kind: str = "oneshot",
    recurrence_json: str | None = None,
) -> str:
    timer_id = new_ulid()
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO agent_timers (
          id, ai_employee_id, scheduled_at, reason, originating_turn_id,
          inherited_trust_label, kind, recurrence_json, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            timer_id,
            ai_employee_id,
            scheduled_at,
            reason,
            originating_turn_id,
            inherited_trust_label,
            kind,
            recurrence_json,
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


def list_pending_timers(
    conn: sqlite3.Connection, *, ai_employee_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Pending timers for an agent — the 'calendar' injected into a turn."""
    rows = conn.execute(
        """
        SELECT id, scheduled_at, reason, kind FROM agent_timers
        WHERE ai_employee_id = ? AND status = 'pending'
        ORDER BY scheduled_at ASC
        LIMIT ?
        """,
        (ai_employee_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def count_pending_timers(conn: sqlite3.Connection, *, ai_employee_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM agent_timers WHERE ai_employee_id = ? AND status = 'pending'",
        (ai_employee_id,),
    ).fetchone()
    return int(row["n"]) if row else 0


def count_wakeups_today(conn: sqlite3.Connection, *, ai_employee_id: str) -> int:
    """Timer-triggered turns for this agent since 00:00 UTC — the daily budget."""
    midnight = datetime.now(tz=UTC).strftime("%Y-%m-%dT00:00:00.000Z")
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM inbound_events
        WHERE target_ai_employee_id = ? AND trigger_type = 'timer' AND received_at >= ?
        """,
        (ai_employee_id, midnight),
    ).fetchone()
    return int(row["n"]) if row else 0


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


def rearm_recurring_timer(
    conn: sqlite3.Connection,
    timer_id: str,
    *,
    recurrence_json: str,
    fired_event_id: str,
) -> str:
    """Advance a recurring timer to its next occurrence, keeping it pending.

    A long-missed window skips straight to the next *future* occurrence rather
    than firing every skipped tick (AUTONOMY_SPEC §5).
    """
    recurrence = json.loads(recurrence_json)
    nxt = next_occurrence(recurrence, after=datetime.now(tz=UTC))
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE agent_timers
        SET scheduled_at = ?, fired_at = ?, fired_event_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (iso_utc(nxt), now, fired_event_id, now, timer_id),
    )
    conn.commit()
    return iso_utc(nxt)


def cancel_timer(conn: sqlite3.Connection, timer_id: str, *, ai_employee_id: str) -> bool:
    cur = conn.execute(
        """
        UPDATE agent_timers SET status = 'cancelled', updated_at = ?
        WHERE id = ? AND ai_employee_id = ? AND status = 'pending'
        """,
        (utc_now_iso(), timer_id, ai_employee_id),
    )
    conn.commit()
    return cur.rowcount > 0


def cancel_agent_timers(conn: sqlite3.Connection, *, ai_employee_id: str) -> int:
    """Cancel all pending timers for an agent. Returns the number cancelled.

    Used when an agent is deactivated so its self-scheduled wakeups stop firing.
    """
    cur = conn.execute(
        """
        UPDATE agent_timers SET status = 'cancelled', updated_at = ?
        WHERE ai_employee_id = ? AND status = 'pending'
        """,
        (utc_now_iso(), ai_employee_id),
    )
    conn.commit()
    return cur.rowcount
