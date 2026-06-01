from __future__ import annotations

import json
import sqlite3

from pidgin.db.chat import insert_message
from pidgin.db.employees import get_agent
from pidgin.llm import stub_chat_reply
from pidgin.recipes import RoleRecipe
from pidgin.runtime.turn import TurnContext, complete_turn, start_turn
from pidgin.types.customization import HireCustomization
from pidgin.util.ids import new_ulid, utc_now_iso


def _is_chat_event(payload: dict) -> bool:
    return "conversation_id" in payload and "message_text" in payload


def execute_turn(conn: sqlite3.Connection, event_row: sqlite3.Row) -> TurnContext:
    payload = json.loads(event_row["payload_json"] or "{}")
    if _is_chat_event(payload):
        return _execute_chat_turn(conn, event_row, payload)
    return _execute_legacy_stub_turn(conn, event_row, payload)


def _execute_legacy_stub_turn(
    conn: sqlite3.Connection,
    event_row: sqlite3.Row,
    payload: dict,
) -> TurnContext:
    from pidgin.runtime.turn import execute_turn_stub

    _ = payload
    return execute_turn_stub(conn, event_row)


def _execute_chat_turn(
    conn: sqlite3.Connection,
    event_row: sqlite3.Row,
    payload: dict,
) -> TurnContext:
    agent_id = event_row["target_ai_employee_id"]
    if not agent_id:
        raise ValueError("Chat event missing target_ai_employee_id")

    agent = get_agent(conn, agent_id)
    if agent is None:
        raise ValueError(f"Unknown agent: {agent_id}")

    snapshot = conn.execute(
        "SELECT bundle_json FROM ai_employee_recipe_snapshots WHERE id = ?",
        (agent["recipe_snapshot_id"],),
    ).fetchone()
    recipe = RoleRecipe.model_validate_json(snapshot["bundle_json"] if snapshot else "{}")
    customization = HireCustomization.from_json(agent["hire_customization_json"])

    ctx = start_turn(conn, event_row)
    conn.execute(
        "UPDATE turns SET conversation_id = ? WHERE id = ?",
        (payload["conversation_id"], ctx.turn_id),
    )
    conn.commit()

    agent_principal = conn.execute(
        "SELECT id FROM principals WHERE ai_employee_id = ? LIMIT 1",
        (agent_id,),
    ).fetchone()
    agent_principal_id = agent_principal["id"] if agent_principal else agent_id

    reply = stub_chat_reply(
        recipe=recipe,
        agent_display_name=agent["display_name"],
        user_message=payload["message_text"],
        customization=customization,
    )

    insert_message(
        conn,
        conversation_id=payload["conversation_id"],
        sender_principal_id=agent_principal_id,
        sender_display_name=agent["display_name"],
        body_text=reply.text,
        originating_turn_id=ctx.turn_id,
    )

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
            agent_id,
            agent["display_name"],
            agent["role_title"],
            payload.get("sender_principal_id", "operator"),
            payload.get("sender_display_name", "You"),
            event_row["trust_label"],
            "accepted_as_instruction",
            reply.action_type,
            json.dumps({"text": reply.text, "conversation_id": payload["conversation_id"]}),
            "executed",
            utc_now_iso(),
        ),
    )
    complete_turn(conn, ctx.turn_id, ctx.inbound_event_id)
    return ctx
