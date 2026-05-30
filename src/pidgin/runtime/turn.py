from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from pidgin.db.connection import SYSTEM_EMPLOYEE_ID
from pidgin.types import ProcessingStatus
from pidgin.util.ids import new_ulid, utc_now_iso


@dataclass
class TurnContext:
    turn_id: str
    inbound_event_id: str
    ai_employee_id: str


def _employee_id(event_row: sqlite3.Row) -> str:
    return event_row["target_ai_employee_id"] or SYSTEM_EMPLOYEE_ID


def start_turn(conn: sqlite3.Connection, event_row: sqlite3.Row) -> TurnContext:
    turn_id = new_ulid()
    now = utc_now_iso()
    employee_id = _employee_id(event_row)
    conn.execute(
        """
        INSERT INTO turns (
          id, ai_employee_id, triggering_event_id, current_status, started_at
        ) VALUES (?, ?, ?, 'running', ?)
        """,
        (turn_id, employee_id, event_row["id"], now),
    )
    conn.execute(
        """
        UPDATE inbound_events
        SET processing_status = ?, picked_up_at = ?, resulting_turn_id = ?
        WHERE id = ?
        """,
        (ProcessingStatus.DISPATCHING.value, now, turn_id, event_row["id"]),
    )
    conn.commit()
    return TurnContext(
        turn_id=turn_id,
        inbound_event_id=event_row["id"],
        ai_employee_id=employee_id,
    )


def complete_turn(conn: sqlite3.Connection, turn_id: str, inbound_event_id: str) -> None:
    now = utc_now_iso()
    conn.execute(
        "UPDATE turns SET current_status = 'completed', ended_at = ? WHERE id = ?",
        (now, turn_id),
    )
    conn.execute(
        """
        UPDATE inbound_events
        SET processing_status = ?, completed_at = ?
        WHERE id = ?
        """,
        (ProcessingStatus.DONE.value, now, inbound_event_id),
    )
    conn.commit()


def execute_turn_stub(conn: sqlite3.Connection, event_row: sqlite3.Row) -> TurnContext:
    """MVP stub: create turn, log placeholder action, mark event done."""
    ctx = start_turn(conn, event_row)
    payload = json.loads(event_row["payload_json"] or "{}")
    conn.execute(
        """
        INSERT INTO agent_action_log (
          id, turn_id, technical_actor, virtual_actor_ai_employee_id,
          virtual_actor_display_name, virtual_actor_role,
          requester_principal_id, requester_display_name,
          trust_label, policy_decision, action_type, action_params_json,
          outcome, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_ulid(),
            ctx.turn_id,
            "runtime",
            ctx.ai_employee_id,
            "Stub Agent",
            "stub",
            "system",
            "System",
            event_row["trust_label"],
            "accepted_as_instruction",
            "read",
            json.dumps({"stub": True, "payload_keys": list(payload.keys())}),
            "executed",
            utc_now_iso(),
        ),
    )
    complete_turn(conn, ctx.turn_id, ctx.inbound_event_id)
    return ctx
