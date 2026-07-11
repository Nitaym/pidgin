"""The change probe behind change-gated wakeups.

A recurring wakeup should only pay for an LLM turn when something actually
changed since that timer last ran. This module is the cheap gate: a pure-DB,
read-only count over five change sources, compared against a baseline
timestamp. No network, no LLM — just indexed queries.

See specs/CHANGE_GATED_WAKEUP_SPEC.html §4.2 (the five sources) and §4.3 (the
baseline).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

# The five change sources, by stable key. The order is the display order in the
# probe snapshot; the set is what an agent's change_sources_json can pare down.
SOURCE_INBOUND_EVENTS = "inbound_events"
SOURCE_TASK_STATE = "task_state"
SOURCE_APPROVALS = "approvals"
SOURCE_WATCHED_RESOURCES = "watched_resources"
SOURCE_DELEGATED_RETURNS = "delegated_returns"

ALL_SOURCES: tuple[str, ...] = (
    SOURCE_INBOUND_EVENTS,
    SOURCE_TASK_STATE,
    SOURCE_APPROVALS,
    SOURCE_WATCHED_RESOURCES,
    SOURCE_DELEGATED_RETURNS,
)

# Which inbound_events trigger types map to which source. A timer/self-prompt is
# the agent's own wakeup, not a change in the world, so neither counts.
_INBOUND_TRIGGERS = ("direct_address", "channel_activity", "inbound_external")
_WATCHER_TRIGGERS = ("watcher",)
_DELEGATION_TRIGGERS = ("peer_delegation",)


def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _agent_principal_id(conn: sqlite3.Connection, ai_employee_id: str) -> str | None:
    row = conn.execute(
        "SELECT id FROM principals WHERE ai_employee_id = ? LIMIT 1",
        (ai_employee_id,),
    ).fetchone()
    return row["id"] if row else None


def _count_inbound(
    conn: sqlite3.Connection, ai_employee_id: str, since: str, triggers: tuple[str, ...]
) -> int:
    placeholders = ",".join("?" for _ in triggers)
    # Skipped timer events are not real activity; exclude them defensively even
    # though they never carry these trigger types.
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM inbound_events
        WHERE target_ai_employee_id = ?
          AND received_at > ?
          AND processing_status != 'skipped'
          AND trigger_type IN ({placeholders})
        """,
        (ai_employee_id, since, *triggers),
    ).fetchone()
    return int(row["n"]) if row else 0


def _count_task_state(
    conn: sqlite3.Connection, principal_id: str | None, since: str, now: str
) -> int:
    if principal_id is None:
        return 0
    # New/unblocked/status moves recorded since the baseline...
    log_row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM tasks_status_log l JOIN tasks t ON t.id = l.task_id
        WHERE t.owner_principal_id = ? AND l.occurred_at > ?
        """,
        (principal_id, since),
    ).fetchone()
    # ...plus tasks whose due_at crossed the (baseline, now] window. A deadline
    # passing is time advancing, not a row insert, so it's computed here.
    due_row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM tasks
        WHERE owner_principal_id = ?
          AND due_at IS NOT NULL
          AND due_at > ? AND due_at <= ?
          AND current_status IN ('open', 'in_progress', 'blocked')
        """,
        (principal_id, since, now),
    ).fetchone()
    return (int(log_row["n"]) if log_row else 0) + (int(due_row["n"]) if due_row else 0)


def _count_approvals(conn: sqlite3.Connection, ai_employee_id: str, since: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM pending_approvals
        WHERE ai_employee_id = ? AND resolved_at IS NOT NULL AND resolved_at > ?
        """,
        (ai_employee_id, since),
    ).fetchone()
    return int(row["n"]) if row else 0


def probe_changes(
    conn: sqlite3.Connection,
    *,
    ai_employee_id: str,
    since: str,
    sources: tuple[str, ...] | list[str] = ALL_SOURCES,
    now: str | None = None,
) -> dict[str, int]:
    """Count qualifying changes per enabled source since ``since`` (an ISO ts).

    Returns a snapshot ``{source_key: count, ...}`` for the enabled sources
    only. The caller runs the turn iff any count is > 0. Cheap and read-only.
    """
    now = now or _now_iso()
    enabled = tuple(s for s in ALL_SOURCES if s in set(sources))
    principal_id = _agent_principal_id(conn, ai_employee_id)
    snapshot: dict[str, int] = {}
    for source in enabled:
        if source == SOURCE_INBOUND_EVENTS:
            snapshot[source] = _count_inbound(conn, ai_employee_id, since, _INBOUND_TRIGGERS)
        elif source == SOURCE_WATCHED_RESOURCES:
            snapshot[source] = _count_inbound(conn, ai_employee_id, since, _WATCHER_TRIGGERS)
        elif source == SOURCE_DELEGATED_RETURNS:
            snapshot[source] = _count_inbound(conn, ai_employee_id, since, _DELEGATION_TRIGGERS)
        elif source == SOURCE_TASK_STATE:
            snapshot[source] = _count_task_state(conn, principal_id, since, now)
        elif source == SOURCE_APPROVALS:
            snapshot[source] = _count_approvals(conn, ai_employee_id, since)
    return snapshot


def total_changes(snapshot: dict[str, int]) -> int:
    return sum(snapshot.values())


# --- per-agent config --------------------------------------------------------
#
# Universal defaults, overridable per agent in the Advanced panel (§4.9). A
# missing/NULL column means "default": gating on, all five sources counted.


def agent_gating_config(
    conn: sqlite3.Connection, ai_employee_id: str
) -> tuple[bool, tuple[str, ...]]:
    """Return (change_gating_enabled, enabled_source_keys) for an agent."""
    row = conn.execute(
        """
        SELECT change_gating_enabled, change_sources_json
        FROM ai_employees WHERE id = ?
        """,
        (ai_employee_id,),
    ).fetchone()
    if row is None:
        return True, ALL_SOURCES
    raw_enabled = row["change_gating_enabled"]
    enabled = True if raw_enabled is None else bool(raw_enabled)
    raw = row["change_sources_json"]
    if not raw:
        return enabled, ALL_SOURCES
    try:
        chosen = json.loads(raw)
    except (ValueError, TypeError):
        return enabled, ALL_SOURCES
    sources = tuple(s for s in ALL_SOURCES if s in set(chosen))
    return enabled, sources or ALL_SOURCES
