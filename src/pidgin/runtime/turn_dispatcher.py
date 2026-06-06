from __future__ import annotations

import logging

from pidgin.runtime.actions import build_egress
from pidgin.runtime.context import TurnEventSink, WorkspaceContext
from pidgin.runtime.turn_executor import TurnExecutor
from pidgin.storage.records import InboundEventRecord, TurnRecord

log = logging.getLogger(__name__)


def dispatch_turn(
    ctx: WorkspaceContext,
    event: InboundEventRecord | str,
    *,
    event_sink: TurnEventSink | None = None,
) -> TurnRecord:
    if isinstance(event, str):
        log.info("[dispatcher] loading event — event_id=%s", event)
        loaded = ctx.turn_store.get_event(event)
        if loaded is None:
            log.error("[dispatcher] event not found — event_id=%s", event)
            raise ValueError(f"Unknown event: {event}")
        event = loaded

    log.info(
        "[dispatcher] dispatching turn — event_id=%s trigger=%s",
        event.id,
        event.trigger_type,
    )
    egress = build_egress(ctx, event)
    try:
        result = TurnExecutor().run(ctx, event=event, egress=egress, event_sink=event_sink)
        log.info("[dispatcher] turn finished — event_id=%s turn_id=%s", event.id, result.id)
        return result
    except Exception as exc:
        log.error(
            "[dispatcher] turn FAILED — event_id=%s error=%s",
            event.id,
            exc,
            exc_info=True,
        )
        raise


def dispatch_pending_turns(
    ctx: WorkspaceContext,
    *,
    batch_size: int = 10,
    event_sink: TurnEventSink | None = None,
) -> int:
    events = ctx.turn_store.fetch_pending_events(limit=batch_size)
    log.info("[dispatcher] processing %d pending event(s)", len(events))
    for event in events:
        dispatch_turn(ctx, event, event_sink=event_sink)
    return len(events)
