from __future__ import annotations

import sqlite3

from pidgin.db.chat import get_or_create_room_conversation, insert_message, list_messages
from pidgin.db.employees import ensure_operator_principal, get_agent_by_handle
from pidgin.db import insert_inbound_event
from pidgin.runtime import run_once
from pidgin.types import InboundEventCreate, TrustLabel, TriggerType


def send_chat_message(
    conn: sqlite3.Connection,
    *,
    room_id: str,
    body_text: str,
    agent_handle: str = "support",
) -> tuple[str, str]:
    agent = get_agent_by_handle(conn, agent_handle)
    if agent is None:
        raise ValueError(f"No agent hired with handle @{agent_handle}")

    operator_id = ensure_operator_principal(conn)
    operator = conn.execute(
        "SELECT display_name FROM principals WHERE id = ?",
        (operator_id,),
    ).fetchone()
    operator_name = operator["display_name"] if operator else "You"

    conversation_id = get_or_create_room_conversation(conn, room_id)
    message_id = insert_message(
        conn,
        conversation_id=conversation_id,
        sender_principal_id=operator_id,
        sender_display_name=operator_name,
        body_text=body_text,
    )

    event_id = insert_inbound_event(
        conn,
        InboundEventCreate(
            trigger_type=TriggerType.DIRECT_ADDRESS,
            target_ai_employee_id=agent["id"],
            sender_principal_id=operator_id,
            trust_label=TrustLabel.INTERNAL_AUTHENTICATED,
            payload={
                "conversation_id": conversation_id,
                "room_id": room_id,
                "message_id": message_id,
                "message_text": body_text,
                "sender_principal_id": operator_id,
                "sender_display_name": operator_name,
            },
        ),
    )
    run_once(conn)
    return message_id, event_id


def get_conversation_messages(conn: sqlite3.Connection, conversation_id: str) -> list[dict]:
    return list_messages(conn, conversation_id)
