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
    from pidgin.storage.sqlite.turn_store import SqliteTurnStore

    store = SqliteTurnStore(conn)
    return [turn.model_dump() for turn in store.list_turns(limit=limit)]


def get_turn(conn: sqlite3.Connection, turn_id: str) -> dict[str, Any] | None:
    from pidgin.storage.sqlite.turn_store import SqliteTurnStore

    store = SqliteTurnStore(conn)
    detail = store.get_turn_detail(turn_id)
    if detail is None:
        return None
    return {
        "turn": detail.turn.model_dump(),
        "triggering_event": (
            detail.triggering_event.model_dump() if detail.triggering_event else None
        ),
        "model_invocations": [row.model_dump() for row in detail.invocations],
        "audit": [row.model_dump() for row in detail.gate_decisions],
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
