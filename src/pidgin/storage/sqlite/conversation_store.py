from __future__ import annotations

import sqlite3

from pidgin.db.chat import insert_message
from pidgin.storage.records import ConversationMessageRecord


class SqliteConversationStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list_messages(
        self, conversation_id: str, limit: int = 100
    ) -> list[ConversationMessageRecord]:
        rows = self._conn.execute(
            """
            SELECT id, sender_principal_id, sender_display_name, body_text, created_at, originating_turn_id
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (conversation_id, limit),
        ).fetchall()
        return [
            ConversationMessageRecord(
                id=row["id"],
                conversation_id=conversation_id,
                sender_principal_id=row["sender_principal_id"],
                sender_display_name=row["sender_display_name"],
                body_text=row["body_text"],
                created_at=row["created_at"],
                originating_turn_id=row["originating_turn_id"],
            )
            for row in rows
        ]

    def insert_message(
        self,
        *,
        conversation_id: str,
        sender_principal_id: str,
        sender_display_name: str,
        body_text: str,
        originating_turn_id: str | None = None,
    ) -> str:
        return insert_message(
            self._conn,
            conversation_id=conversation_id,
            sender_principal_id=sender_principal_id,
            sender_display_name=sender_display_name,
            body_text=body_text,
            originating_turn_id=originating_turn_id,
        )
