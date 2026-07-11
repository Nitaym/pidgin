"""Read/write the per-agent change-gated wakeup config (the Advanced panel).

Universal defaults live in the runtime; these three columns let an operator
override them per agent. A NULL column means "use the default". See
specs/CHANGE_GATED_WAKEUP_SPEC.html §4.9.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from pidgin.db.change_probe import ALL_SOURCES
from pidgin.util.ids import utc_now_iso

DEFAULT_WAKE_TIMES: tuple[str, ...] = ("09:00",)

# Source key → human label for the config UI. Order is display order.
SOURCE_LABELS: dict[str, str] = {
    "inbound_events": "New messages & email",
    "task_state": "Task changes (due, unblocked, new)",
    "approvals": "Approvals resolved",
    "watched_resources": "Watched resources changed",
    "delegated_returns": "Delegated work returned",
}


def read_change_gating_config(conn: sqlite3.Connection, ai_employee_id: str) -> dict[str, Any]:
    """Resolved config for one agent, with universal defaults filled in."""
    row = conn.execute(
        """
        SELECT change_gating_enabled, guaranteed_wake_times_json, change_sources_json
        FROM ai_employees WHERE id = ?
        """,
        (ai_employee_id,),
    ).fetchone()
    if row is None:
        raise KeyError(ai_employee_id)

    enabled_raw = row["change_gating_enabled"]
    enabled = True if enabled_raw is None else bool(enabled_raw)

    wake_times = _loads_list(row["guaranteed_wake_times_json"]) or list(DEFAULT_WAKE_TIMES)

    chosen = _loads_list(row["change_sources_json"])
    if chosen is None:
        sources = list(ALL_SOURCES)
    else:
        sources = [s for s in ALL_SOURCES if s in set(chosen)]

    return {
        "change_gating_enabled": enabled,
        "guaranteed_wake_times": [str(t) for t in wake_times],
        "change_sources": sources,
        "all_sources": [{"key": k, "label": SOURCE_LABELS[k]} for k in ALL_SOURCES],
    }


def write_change_gating_config(
    conn: sqlite3.Connection,
    ai_employee_id: str,
    *,
    change_gating_enabled: bool,
    guaranteed_wake_times: list[str],
    change_sources: list[str],
) -> None:
    """Persist the three knobs. Wake times and sources are validated/normalized."""
    times = _validate_wake_times(guaranteed_wake_times)
    sources = [s for s in ALL_SOURCES if s in set(change_sources)] or list(ALL_SOURCES)
    conn.execute(
        """
        UPDATE ai_employees
        SET change_gating_enabled = ?, guaranteed_wake_times_json = ?,
            change_sources_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            1 if change_gating_enabled else 0,
            json.dumps(times),
            json.dumps(sources),
            utc_now_iso(),
            ai_employee_id,
        ),
    )
    conn.commit()


def _loads_list(raw: str | None) -> list | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, list) else None


def _validate_wake_times(times: list[str]) -> list[str]:
    """Keep well-formed HH:MM entries, deduped and sorted; fall back to default."""
    cleaned: list[str] = []
    for raw in times:
        text = str(raw).strip()
        hh, _, mm = text.partition(":")
        if hh.isdigit() and mm.isdigit() and 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59:
            cleaned.append(f"{int(hh):02d}:{int(mm):02d}")
    ordered = sorted(set(cleaned))
    return ordered or list(DEFAULT_WAKE_TIMES)
