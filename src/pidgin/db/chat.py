from __future__ import annotations

import sqlite3
from typing import Any

from pidgin.util.ids import new_ulid, utc_now_iso


def get_room_by_name(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM rooms WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def create_room(
    conn: sqlite3.Connection,
    *,
    name: str,
    purpose: str | None = None,
    visibility: str = "public",
) -> str:
    room_id = new_ulid()
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO rooms (
          id, name, purpose, modality, visibility, created_at, updated_at
        ) VALUES (?, ?, ?, 'pidgin_chat', ?, ?, ?)
        """,
        (room_id, name, purpose, visibility, now, now),
    )
    conn.commit()
    return room_id


def ensure_room_member(conn: sqlite3.Connection, room_id: str, principal_id: str) -> None:
    existing = conn.execute(
        "SELECT id FROM room_members WHERE room_id = ? AND principal_id = ?",
        (room_id, principal_id),
    ).fetchone()
    if existing is not None:
        return
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO room_members (id, room_id, principal_id, joined_at)
        VALUES (?, ?, ?, ?)
        """,
        (new_ulid(), room_id, principal_id, now),
    )
    conn.commit()


def get_or_create_room_conversation(conn: sqlite3.Connection, room_id: str) -> str:
    row = conn.execute(
        """
        SELECT id FROM conversations
        WHERE room_id = ? AND modality = 'pidgin_chat'
        ORDER BY created_at LIMIT 1
        """,
        (room_id,),
    ).fetchone()
    if row is not None:
        return row["id"]

    conversation_id = new_ulid()
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO conversations (
          id, room_id, modality, started_at, created_at, updated_at
        ) VALUES (?, ?, 'pidgin_chat', ?, ?, ?)
        """,
        (conversation_id, room_id, now, now, now),
    )
    conn.commit()
    return conversation_id


def insert_message(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    sender_principal_id: str,
    sender_display_name: str,
    body_text: str,
    originating_event_id: str | None = None,
    originating_turn_id: str | None = None,
) -> str:
    message_id = new_ulid()
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO messages (
          id, conversation_id, sender_principal_id, sender_display_name,
          modality, body_text, body_format, originating_event_id,
          originating_turn_id, created_at
        ) VALUES (?, ?, ?, ?, 'pidgin_chat', ?, 'text', ?, ?, ?)
        """,
        (
            message_id,
            conversation_id,
            sender_principal_id,
            sender_display_name,
            body_text,
            originating_event_id,
            originating_turn_id,
            now,
        ),
    )
    conn.commit()
    return message_id


def list_messages(conn: sqlite3.Connection, conversation_id: str, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, sender_display_name, body_text, created_at, originating_turn_id
        FROM messages
        WHERE conversation_id = ?
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (conversation_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def list_rooms(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, purpose, modality FROM rooms ORDER BY name ASC"
    ).fetchall()
    return [dict(row) for row in rows]
