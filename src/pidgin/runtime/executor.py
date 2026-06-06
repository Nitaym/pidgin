"""Backward-compatible shim — use turn_dispatcher.dispatch_turn."""

from __future__ import annotations

import sqlite3

from pidgin.runtime.scheduler import workspace_context_from_conn
from pidgin.runtime.turn import TurnContext, execute_turn_stub
from pidgin.runtime.turn_dispatcher import dispatch_turn


def execute_turn(conn: sqlite3.Connection, event_row: sqlite3.Row) -> TurnContext:
    ctx = workspace_context_from_conn(conn)
    event_id = event_row["id"]
    turn = dispatch_turn(ctx, event_id)
    return TurnContext(
        turn_id=turn.id,
        inbound_event_id=event_id,
        ai_employee_id=turn.ai_employee_id,
    )


__all__ = ["execute_turn", "execute_turn_stub"]
