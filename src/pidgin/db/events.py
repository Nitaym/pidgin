from __future__ import annotations

import json
import sqlite3

from pidgin.types import InboundEventCreate, ProcessingStatus
from pidgin.util.ids import new_ulid, utc_now_iso


def insert_inbound_event(conn: sqlite3.Connection, event: InboundEventCreate) -> str:
    event_id = new_ulid()
    conn.execute(
        """
        INSERT INTO inbound_events (
          id, trigger_type, target_ai_employee_id, sender_principal_id,
          trust_label, resumes_turn_id, parent_turn_id, payload_json,
          processing_status, received_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            event.trigger_type.value,
            event.target_ai_employee_id,
            event.sender_principal_id,
            event.trust_label.value,
            event.resumes_turn_id,
            event.parent_turn_id,
            json.dumps(event.payload),
            ProcessingStatus.PENDING.value,
            utc_now_iso(),
        ),
    )
    conn.commit()
    return event_id


def fetch_pending_events(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM inbound_events
            WHERE processing_status = ?
            ORDER BY received_at ASC
            LIMIT ?
            """,
            (ProcessingStatus.PENDING.value, limit),
        ).fetchall()
    )
