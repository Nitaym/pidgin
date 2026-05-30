from __future__ import annotations

import json
import sqlite3
from typing import Any


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def list_inbound_events(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, trigger_type, processing_status, trust_label,
               target_ai_employee_id, received_at, picked_up_at, completed_at,
               resulting_turn_id, payload_json
        FROM inbound_events
        ORDER BY received_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def list_turns(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, ai_employee_id, triggering_event_id, current_status,
               started_at, ended_at, conversation_id
        FROM turns
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_turn(conn: sqlite3.Connection, turn_id: str) -> dict[str, Any] | None:
    turn_row = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
    if turn_row is None:
        return None

    event_row = conn.execute(
        "SELECT * FROM inbound_events WHERE id = ?",
        (turn_row["triggering_event_id"],),
    ).fetchone()
    audit_rows = conn.execute(
        """
        SELECT * FROM agent_action_log
        WHERE turn_id = ?
        ORDER BY occurred_at ASC
        """,
        (turn_id,),
    ).fetchall()

    return {
        "turn": _row_to_dict(turn_row),
        "triggering_event": _row_to_dict(event_row) if event_row else None,
        "audit": [_row_to_dict(row) for row in audit_rows],
    }


def list_audit_log(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, turn_id, action_type, policy_decision, outcome,
               trust_label, occurred_at, action_params_json
        FROM agent_action_log
        ORDER BY occurred_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    items = [_row_to_dict(row) for row in rows]
    for item in items:
        raw = item.get("action_params_json")
        if isinstance(raw, str):
            try:
                item["action_params"] = json.loads(raw)
            except json.JSONDecodeError:
                item["action_params"] = raw
    return items
