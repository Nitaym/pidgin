from __future__ import annotations

import sqlite3

from pidgin.db import insert_inbound_event
from pidgin.types import InboundEventCreate, TriggerType, TrustLabel


def inject_test_event(
    conn: sqlite3.Connection,
    *,
    message: str = "Admin test event",
    trust_label: TrustLabel = TrustLabel.INTERNAL_AUTHENTICATED,
) -> str:
    return insert_inbound_event(
        conn,
        InboundEventCreate(
            trigger_type=TriggerType.DIRECT_ADDRESS,
            trust_label=trust_label,
            payload={"message": message, "source": "admin"},
        ),
    )


def process_pending_events(conn: sqlite3.Connection) -> int:
    # Lazy import: pidgin.runtime's prompt assembly imports pidgin.services,
    # so a top-level import here is circular when runtime loads first.
    from pidgin.runtime import run_once

    return run_once(conn)
