from __future__ import annotations

import sqlite3
import time

from pidgin.db.events import fetch_pending_events
from pidgin.runtime.executor import execute_turn


def run_once(conn: sqlite3.Connection, batch_size: int = 10) -> int:
    events = fetch_pending_events(conn, limit=batch_size)
    for row in events:
        execute_turn(conn, row)
    return len(events)


def run_loop(conn: sqlite3.Connection, poll_interval_seconds: float = 1.0) -> None:
    while True:
        processed = run_once(conn)
        if processed == 0:
            time.sleep(poll_interval_seconds)
