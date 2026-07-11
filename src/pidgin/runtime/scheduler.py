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


# A self-running agent can wake itself without a human in the loop, so an
# unbounded recipe (or an injection-induced loop) must be capped. Per
# AGENT_RUNTIME_SPEC Open Decision 4 / AUTONOMY_SPEC §6.
_DEFAULT_MAX_WAKEUPS_PER_DAY = 100


def _timer_fired_message(timer: dict, requester: str) -> str:
    """The instruction the agent sees when a timer fires, shaped by kind."""
    if timer["kind"] == "bootstrap":
        # The reason *is* the bootstrap brief — deliver it verbatim.
        return timer["reason"]
    recurring = timer["kind"] == "recurring"
    lead = "[Recurring check-in]" if recurring else "[Scheduled timer fired]"
    by = f" (requested by {requester})" if requester else ""
    tail = (
        "Act on it now. Use say to reply in the conversation where this was "
        "scheduled, or post / escalate to reach a specific person or channel."
        if timer["originating_turn_id"]
        else "Act on it now. You have no conversation to reply into — use "
        "open_task, post, or escalate to produce a visible result."
    )
    return f"{lead} You scheduled this for yourself{by}: {timer['reason']}\n{tail}"


def _is_gated(conn: sqlite3.Connection, timer: dict) -> bool:
    """True if this due timer should be probed for change before running.

    Only recurring timers are gated, and only once they have a baseline to
    compare against (first fire always runs). ``always_run`` timers — the
    guaranteed daily floor and compliance ticks — are never gated, and an
    operator can disable gating per agent. See spec §4.4.
    """
    from pidgin.db.change_probe import agent_gating_config

    if timer["kind"] != "recurring" or timer["always_run"] or not timer["last_ran_at"]:
        return False
    enabled, _sources = agent_gating_config(conn, timer["ai_employee_id"])
    return enabled


def _record_skipped_wakeup(conn: sqlite3.Connection, timer: dict, snapshot: dict) -> str:
    """Materialize a skipped wakeup: an anchored (never-dispatched) event and a
    terminal ``skipped`` turn carrying the probe snapshot that justified it.

    The turn is a first-class, auditable object (spec §4.7) — no LLM ran, so it
    is created already-terminal and its event is marked ``skipped`` so the
    dispatcher never picks it up.
    """
    import json

    from pidgin.util.ids import new_ulid, utc_now_iso

    now = utc_now_iso()
    event_id = new_ulid()
    turn_id = new_ulid()
    conn.execute(
        """
        INSERT INTO inbound_events (
          id, trigger_type, target_ai_employee_id, sender_principal_id,
          trust_label, payload_json, processing_status, resulting_turn_id,
          completed_at, received_at
        ) VALUES (?, 'timer', ?, NULL, ?, ?, 'skipped', ?, ?, ?)
        """,
        (
            event_id,
            timer["ai_employee_id"],
            timer["inherited_trust_label"],
            json.dumps({"timer_id": timer["id"], "timer_reason": timer["reason"]}),
            turn_id,
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO turns (
          id, ai_employee_id, conversation_id, triggering_event_id,
          current_status, skip_reason, probe_snapshot_json, started_at, ended_at
        ) VALUES (?, ?, NULL, ?, 'skipped', 'nothing_changed', ?, ?, ?)
        """,
        (
            turn_id,
            timer["ai_employee_id"],
            event_id,
            json.dumps({"baseline": timer["last_ran_at"], "counts": snapshot}),
            now,
            now,
        ),
    )
    conn.commit()
    return event_id


def fire_due_timers(conn: sqlite3.Connection, *, limit: int = 10) -> int:
    """Convert due agent_timers into inbound_events (trigger_type=timer).

    Handles three kinds: oneshot (fire + done), bootstrap (fire + done, brief
    delivered verbatim), and recurring (fire + re-arm to next occurrence).
    Self-anchored timers (no originating_turn_id) fire with no conversation
    context. Per-agent daily wakeup budget defers over-cap timers.

    Change-gating: a recurring wakeup whose cheap DB probe finds nothing changed
    since it last ran is recorded as a ``skipped`` turn and re-armed without ever
    building an LLM turn — it draws no wakeup budget and does not advance the
    timer's baseline. The return value counts only real (dispatched) wakeups.
    """
    import json

    from pidgin.db import insert_inbound_event
    from pidgin.db.change_probe import probe_changes, total_changes
    from pidgin.db.timers import (
        count_wakeups_today,
        list_due_timers,
        mark_timer_fired,
        rearm_recurring_timer,
        stamp_timer_ran,
    )
    from pidgin.types import InboundEventCreate, TriggerType, TrustLabel

    fired = 0
    for timer in list_due_timers(conn, limit=limit):
        # Change gate: probe before paying for a turn. Nothing changed → skip.
        if _is_gated(conn, timer):
            from pidgin.db.change_probe import agent_gating_config

            _enabled, sources = agent_gating_config(conn, timer["ai_employee_id"])
            snapshot = probe_changes(
                conn,
                ai_employee_id=timer["ai_employee_id"],
                since=timer["last_ran_at"],
                sources=sources,
            )
            if total_changes(snapshot) == 0:
                skip_event_id = _record_skipped_wakeup(conn, timer, snapshot)
                if timer["recurrence_json"]:
                    rearm_recurring_timer(
                        conn, timer["id"],
                        recurrence_json=timer["recurrence_json"], fired_event_id=skip_event_id,
                    )
                log.info(
                    "[scheduler] recurring wakeup skipped (nothing changed) — "
                    "timer_id=%s snapshot=%s", timer["id"], snapshot,
                )
                continue

        if count_wakeups_today(conn, ai_employee_id=timer["ai_employee_id"]) >= _DEFAULT_MAX_WAKEUPS_PER_DAY:
            log.warning(
                "[scheduler] wakeup budget exhausted — agent=%s timer_id=%s deferred",
                timer["ai_employee_id"], timer["id"],
            )
            continue

        origin_turn_id = timer["originating_turn_id"]
        origin = _timer_origin(conn, origin_turn_id) if origin_turn_id else None
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
        payload.update(
            {
                "message_text": _timer_fired_message(timer, requester),
                "timer_id": timer["id"],
                "timer_reason": timer["reason"],
                "originating_turn_id": origin_turn_id,
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
                parent_turn_id=origin_turn_id,
            ),
        )
        if timer["kind"] == "recurring" and timer["recurrence_json"]:
            # A real run advances the baseline the change probe measures against.
            stamp_timer_ran(conn, timer["id"])
            nxt = rearm_recurring_timer(
                conn, timer["id"],
                recurrence_json=timer["recurrence_json"], fired_event_id=event_id,
            )
            log.info(
                "[scheduler] recurring timer fired — timer_id=%s event_id=%s next=%s",
                timer["id"], event_id, nxt,
            )
        else:
            mark_timer_fired(conn, timer["id"], fired_event_id=event_id)
            log.info(
                "[scheduler] timer fired — timer_id=%s kind=%s event_id=%s",
                timer["id"], timer["kind"], event_id,
            )
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
    processed = dispatch_pending_turns(ctx, batch_size=batch_size)
    if processed and bridge is not None:
        # Coarse diagnostics signal — lets the Diagnostics page live-refresh its
        # events/turns/audit tables as background turns complete.
        from pidgin.realtime import publish_workspace_event

        publish_workspace_event(bridge, "turn.completed", {"processed": processed})
    return processed


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
