from __future__ import annotations

import json
import sqlite3
from typing import Any

from pidgin.util.ids import new_ulid, utc_now_iso


def get_agent_conversation(conn: sqlite3.Connection, handle: str) -> dict[str, Any] | None:
    from pidgin.db.employees import get_agent_by_handle

    agent = get_agent_by_handle(conn, handle)
    if agent is None:
        return None
    row = conn.execute(
        """
        SELECT id, ai_employee_id, modality
        FROM conversations
        WHERE ai_employee_id = ? AND modality = 'pidgin_chat'
        ORDER BY created_at ASC
        LIMIT 1
        """,
        (agent["id"],),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "ai_employee_id": row["ai_employee_id"],
        "modality": row["modality"],
    }


def ensure_agent_conversation(conn: sqlite3.Connection, handle: str) -> dict[str, Any]:
    existing = get_agent_conversation(conn, handle)
    if existing is not None:
        return existing

    from pidgin.db.employees import get_agent_by_handle

    agent = get_agent_by_handle(conn, handle)
    if agent is None:
        raise ValueError(f"No agent with handle @{handle}")

    conversation_id = create_agent_conversation(conn, agent["id"])
    return {
        "id": conversation_id,
        "ai_employee_id": agent["id"],
        "modality": "pidgin_chat",
    }


def create_agent_conversation(conn: sqlite3.Connection, ai_employee_id: str) -> str:
    conversation_id = new_ulid()
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO conversations (
          id, ai_employee_id, modality, started_at, created_at, updated_at
        ) VALUES (?, ?, 'pidgin_chat', ?, ?, ?)
        """,
        (conversation_id, ai_employee_id, now, now, now),
    )
    conn.commit()
    return conversation_id


def get_or_create_agent_conversation(conn: sqlite3.Connection, ai_employee_id: str) -> str:
    row = conn.execute(
        """
        SELECT id FROM conversations
        WHERE ai_employee_id = ? AND modality = 'pidgin_chat'
        ORDER BY created_at LIMIT 1
        """,
        (ai_employee_id,),
    ).fetchone()
    if row is not None:
        return row["id"]
    return create_agent_conversation(conn, ai_employee_id)


def insert_message(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    sender_principal_id: str,
    sender_display_name: str,
    body_text: str,
    originating_event_id: str | None = None,
    originating_turn_id: str | None = None,
    attachments_json: str | None = None,
) -> str:
    message_id = new_ulid()
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO messages (
          id, conversation_id, sender_principal_id, sender_display_name,
          modality, body_text, body_format, attachments_json, originating_event_id,
          originating_turn_id, created_at
        ) VALUES (?, ?, ?, ?, 'pidgin_chat', ?, 'text', ?, ?, ?, ?)
        """,
        (
            message_id,
            conversation_id,
            sender_principal_id,
            sender_display_name,
            body_text,
            attachments_json,
            originating_event_id,
            originating_turn_id,
            now,
        ),
    )
    conn.commit()

    # Notify any connected UI that this conversation changed so badges and open
    # threads refetch. Thin/invalidation event — carries only ids to scope the
    # refetch. Fires for every write, including background/autonomous turns
    # (which is the path plain polling used to miss).
    from pidgin.realtime import publish_workspace_event

    publish_workspace_event(
        conn,
        "message.created",
        {
            "conversation_id": conversation_id,
            "agent_authored": originating_turn_id is not None,
        },
    )
    return message_id


def list_messages(conn: sqlite3.Connection, conversation_id: str, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, sender_display_name, body_text, created_at, originating_turn_id, attachments_json
        FROM messages
        WHERE conversation_id = ?
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (conversation_id, limit),
    ).fetchall()
    messages = [dict(row) for row in rows]

    # Chat messages that requested owner approval carry a pending_approval_id in
    # attachments_json — join in its live status so the frontend can render
    # inline Approve/Reject buttons right on that message (not just the
    # separate Approvals page) and knows when they've already been resolved.
    approval_ids: list[str] = []
    for message in messages:
        raw = message.pop("attachments_json", None)
        message["pending_approval_id"] = None
        message["pending_approval_status"] = None
        if raw:
            try:
                attachments = json.loads(raw)
            except (TypeError, ValueError):
                attachments = {}
            approval_id = (
                attachments.get("pending_approval_id") if isinstance(attachments, dict) else None
            )
            if approval_id:
                message["pending_approval_id"] = approval_id
                approval_ids.append(approval_id)

    if approval_ids:
        placeholders = ", ".join("?" for _ in approval_ids)
        status_rows = conn.execute(
            f"SELECT id, current_status FROM pending_approvals WHERE id IN ({placeholders})",
            approval_ids,
        ).fetchall()
        status_by_id = {row["id"]: row["current_status"] for row in status_rows}
        for message in messages:
            approval_id = message["pending_approval_id"]
            if approval_id:
                message["pending_approval_status"] = status_by_id.get(approval_id)

    return messages
