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


def list_model_invocations(
    conn: sqlite3.Connection,
    limit: int = 50,
    after: str | None = None,
) -> list[dict[str, Any]]:
    """Every LLM request/response across all turns, newest first.

    `after` is an invocation id cursor (ULIDs sort by time): pass the newest id
    you have seen to fetch only invocations recorded since then — this is what
    lets the inspector tail live traffic cheaply.
    """
    base_sql = """
        SELECT mi.id, mi.turn_id, mi.sequence_in_turn, mi.provider, mi.model_id,
               mi.request_messages_json, mi.request_tools_json, mi.response_json,
               mi.input_tokens, mi.output_tokens, mi.cost_usd_micros,
               mi.latency_ms, mi.error_text, mi.invoked_at,
               t.ai_employee_id, t.conversation_id, t.current_status AS turn_status,
               e.trigger_type, e.payload_json AS event_payload_json,
               a.display_name AS agent_display_name, a.handle AS agent_handle
        FROM model_invocations mi
        LEFT JOIN turns t ON t.id = mi.turn_id
        LEFT JOIN inbound_events e ON e.id = t.triggering_event_id
        LEFT JOIN ai_employees a ON a.id = t.ai_employee_id
    """
    if after:
        rows = conn.execute(
            base_sql + " WHERE mi.id > ? ORDER BY mi.id DESC LIMIT ?",
            (after, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            base_sql + " ORDER BY mi.id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        item = _row_to_dict(row)
        item["request_messages"] = _loads_or(item.pop("request_messages_json"), [])
        item["request_tools"] = _loads_or(item.pop("request_tools_json"), [])
        item["response"] = _loads_or(item.pop("response_json"), None)
        payload = _loads_or(item.pop("event_payload_json"), {})
        item["source"] = (
            payload.get("connector_type", "pidgin_chat")
            if isinstance(payload, dict)
            else "pidgin_chat"
        )
        items.append(item)
    return items


def _loads_or(raw: Any, default: Any) -> Any:
    if not isinstance(raw, str) or not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


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
