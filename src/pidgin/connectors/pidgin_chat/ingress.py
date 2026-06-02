from __future__ import annotations

import sqlite3

from pidgin.connectors.types import ResourceUri
from pidgin.db import insert_inbound_event
from pidgin.types import InboundEventCreate, TriggerType, TrustLabel


def build_ingress_payload(
    *,
    connector_installation_id: str | None,
    conversation_id: str,
    room_id: str,
    message_id: str,
    message_text: str,
    sender_principal_id: str,
    sender_display_name: str,
    raw_ref: dict | None = None,
) -> dict:
    return {
        "connector_type": "pidgin_chat",
        "connector_installation_id": connector_installation_id,
        "external_channel_id": room_id,
        "external_thread_id": conversation_id,
        "message_text": message_text,
        "message_id": message_id,
        "sender_principal_id": sender_principal_id,
        "sender_display_name": sender_display_name,
        "room_id": room_id,
        "conversation_id": conversation_id,
        "raw_ref": raw_ref or {},
    }


def enqueue_direct_address(
    conn: sqlite3.Connection,
    *,
    target_ai_employee_id: str,
    conversation_id: str,
    room_id: str,
    message_id: str,
    message_text: str,
    sender_principal_id: str,
    sender_display_name: str,
    trust_label: TrustLabel = TrustLabel.INTERNAL_AUTHENTICATED,
    run_turn: bool = True,
) -> str:
    event_id = insert_inbound_event(
        conn,
        InboundEventCreate(
            trigger_type=TriggerType.DIRECT_ADDRESS,
            target_ai_employee_id=target_ai_employee_id,
            sender_principal_id=sender_principal_id,
            trust_label=trust_label,
            payload=build_ingress_payload(
                connector_installation_id=None,
                conversation_id=conversation_id,
                room_id=room_id,
                message_id=message_id,
                message_text=message_text,
                sender_principal_id=sender_principal_id,
                sender_display_name=sender_display_name,
            ),
        ),
    )
    if run_turn:
        from pidgin.runtime.scheduler import run_once

        run_once(conn)
    return event_id


def conversation_resource_uri(conversation_id: str) -> ResourceUri:
    return ResourceUri(prefix="pidgin_chat", kind="conversation", resource_id=conversation_id)
