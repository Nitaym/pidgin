from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

from pidgin.llm.config import load_llm_config
from pidgin.runtime.context import WorkspaceContext
from pidgin.runtime.turn_dispatcher import dispatch_pending_turns
from pidgin.storage.sqlite.conversation_store import SqliteConversationStore
from pidgin.storage.sqlite.turn_store import SqliteTurnStore
from pidgin.workspace.factory import _ensure_llm_providers
from pidgin.workspace.manager import WorkspacePaths

log = logging.getLogger(__name__)


# Origin-event payload keys copied onto the timer event so the resulting turn
# keeps its conversation: egress routes `say` back to where the timer was
# scheduled, and the agent knows who asked.
_TIMER_CONTEXT_KEYS = (
    "connector_type",
    "connector_installation_id",
    "external_channel_id",
    "external_thread_id",
    "conversation_id",
    "sender_principal_id",
    "sender_display_name",
)


def _timer_origin(conn: sqlite3.Connection, originating_turn_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT ie.payload_json, ie.sender_principal_id
        FROM turns t JOIN inbound_events ie ON ie.id = t.triggering_event_id
        WHERE t.id = ?
        """,
        (originating_turn_id,),
    ).fetchone()


def fire_due_timers(conn: sqlite3.Connection, *, limit: int = 10) -> int:
    """Convert due agent_timers into inbound_events (trigger_type=timer)."""
    import json

    from pidgin.db import insert_inbound_event
    from pidgin.db.timers import list_due_timers, mark_timer_fired
    from pidgin.types import InboundEventCreate, TriggerType, TrustLabel

    fired = 0
    for timer in list_due_timers(conn, limit=limit):
        origin = _timer_origin(conn, timer["originating_turn_id"])
        origin_payload = json.loads(origin["payload_json"]) if origin else {}
        payload = {
            key: origin_payload[key]
            for key in _TIMER_CONTEXT_KEYS
            if origin_payload.get(key)
        }
        requester = str(payload.get("sender_display_name") or "")
        if not requester and origin and origin["sender_principal_id"]:
            principal = conn.execute(
                "SELECT display_name FROM principals WHERE id = ?",
                (origin["sender_principal_id"],),
            ).fetchone()
            requester = principal["display_name"] if principal else ""
        message = (
            f"[Scheduled timer fired] You previously scheduled this follow-up"
            f"{f' (requested by {requester})' if requester else ''}: "
            f"{timer['reason']}\n"
            "Act on it now. Use say to reply in the conversation where this was "
            "scheduled, or post to reach a specific person or channel."
        )
        payload.update(
            {
                "message_text": message,
                "timer_id": timer["id"],
                "timer_reason": timer["reason"],
                "originating_turn_id": timer["originating_turn_id"],
            }
        )
        event_id = insert_inbound_event(
            conn,
            InboundEventCreate(
                trigger_type=TriggerType.TIMER,
                target_ai_employee_id=timer["ai_employee_id"],
                sender_principal_id=origin["sender_principal_id"] if origin else None,
                trust_label=TrustLabel(timer["inherited_trust_label"]),
                payload=payload,
                parent_turn_id=timer["originating_turn_id"],
            ),
        )
        mark_timer_fired(conn, timer["id"], fired_event_id=event_id)
        log.info("[scheduler] timer fired — timer_id=%s event_id=%s", timer["id"], event_id)
        fired += 1
    return fired


def workspace_context_from_conn(conn: sqlite3.Connection) -> WorkspaceContext:
    _ensure_llm_providers()
    workspace = conn.execute("SELECT id, settings_json FROM workspace LIMIT 1").fetchone()
    workspace_id = workspace["id"] if workspace else "default"
    settings_json = workspace["settings_json"] if workspace else None
    db_list = conn.execute("PRAGMA database_list").fetchone()
    db_path = Path(db_list[2] if db_list else "db.sqlite")
    paths = WorkspacePaths(root=db_path.parent)
    return WorkspaceContext(
        workspace_id=workspace_id,
        paths=paths,
        turn_store=SqliteTurnStore(conn),
        conversation_store=SqliteConversationStore(conn),
        llm_config=load_llm_config(settings_json),
        db_bridge=conn,
    )


def run_once(
    conn: sqlite3.Connection | None = None,
    *,
    ctx: WorkspaceContext | None = None,
    batch_size: int = 10,
) -> int:
    if ctx is None:
        if conn is None:
            return 0
        ctx = workspace_context_from_conn(conn)
    bridge = ctx.db_bridge
    if bridge is not None:
        try:
            fire_due_timers(bridge)
        except Exception:  # noqa: BLE001 — a broken timer must not stall dispatch
            log.exception("[scheduler] fire_due_timers failed")
    return dispatch_pending_turns(ctx, batch_size=batch_size)


def run_loop(
    conn: sqlite3.Connection,
    poll_interval_seconds: float = 1.0,
    heartbeat_interval_seconds: float = 60.0,
) -> None:
    last_heartbeat = time.monotonic()
    while True:
        processed = run_once(conn)
        now = time.monotonic()
        if now - last_heartbeat >= heartbeat_interval_seconds:
            log.debug("[scheduler] polling for events")
            last_heartbeat = now
        if processed == 0:
            time.sleep(poll_interval_seconds)
