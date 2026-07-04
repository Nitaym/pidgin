"""In-process fan-out pub/sub for workspace-scoped UI notifications.

Unlike ``TurnEventBus`` (one queue per turn, single consumer — used to stream
one LLM response), this bus broadcasts each event to *every* subscriber of a
workspace. That supports many browser tabs and many topics over a single SSE
connection, which is what the sidebar badges, chat threads and diagnostics
pages subscribe to.

Design notes (see the realtime-events architecture discussion):
  * Thin / invalidation events — payloads carry only the ids needed to scope a
    refetch, never full domain objects. The client re-reads via REST, so REST
    stays the single source of truth and there is no client/server drift.
  * Ephemeral, in-process — a slow or disconnected client simply misses events
    and self-heals by refetching on its next event or on reconnect. This is
    correct only because events are thin. If we ever run more than one process,
    a durable outbox (writers append to a table, a publisher tails it) would
    replace this module; the SSE endpoint and the frontend would not change.

The module imports only the standard library so it can be imported from any
layer (the DB write helpers publish through it) without risking a circular
import.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class WorkspaceEvent:
    """A thin notification: a topic plus just enough ids to scope a refetch."""

    topic: str
    payload: dict[str, Any] = field(default_factory=dict)


class WorkspaceEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[WorkspaceEvent]]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the HTTP event loop so publishes from worker/threadpool
        threads can hand events across via ``call_soon_threadsafe``."""
        self._loop = loop

    def subscribe(self, workspace_id: str) -> asyncio.Queue[WorkspaceEvent]:
        queue: asyncio.Queue[WorkspaceEvent] = asyncio.Queue(maxsize=1000)
        self._subscribers.setdefault(workspace_id, set()).add(queue)
        return queue

    def unsubscribe(self, workspace_id: str, queue: asyncio.Queue[WorkspaceEvent]) -> None:
        subs = self._subscribers.get(workspace_id)
        if subs is None:
            return
        subs.discard(queue)
        if not subs:
            self._subscribers.pop(workspace_id, None)

    def publish(self, workspace_id: str, event: WorkspaceEvent) -> None:
        """Fan an event out to every subscriber of ``workspace_id``.

        Safe to call from any thread: DB writes happen on the worker thread and
        on FastAPI's sync-route threadpool, neither of which runs the event
        loop, so the fan-out is marshalled onto the loop thread.
        """
        loop = self._loop
        if loop is not None:
            try:
                running: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not loop:
                loop.call_soon_threadsafe(self._fan_out, workspace_id, event)
                return
        self._fan_out(workspace_id, event)

    def _fan_out(self, workspace_id: str, event: WorkspaceEvent) -> None:
        for queue in list(self._subscribers.get(workspace_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A wedged client must not block others; drop and let it
                # self-heal by refetching on its next event / reconnect.
                log.debug("workspace event queue full for %s; dropping", workspace_id)


workspace_event_bus = WorkspaceEventBus()


def _workspace_id_from_conn(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT id FROM workspace LIMIT 1").fetchone()
    if row is None:
        return None
    # Rows may be sqlite3.Row (mapping) or a plain tuple depending on factory.
    try:
        return str(row["id"])
    except (TypeError, IndexError, KeyError):
        return str(row[0])


def publish_workspace_event(
    conn: sqlite3.Connection, topic: str, payload: dict[str, Any] | None = None
) -> None:
    """Best-effort publish scoped to the (singleton) workspace behind ``conn``.

    Never raises: a realtime notification must not break the DB write it rides
    behind. Callers invoke this right after ``conn.commit()``.
    """
    try:
        workspace_id = _workspace_id_from_conn(conn)
        if workspace_id is None:
            return
        workspace_event_bus.publish(
            workspace_id, WorkspaceEvent(topic=topic, payload=payload or {})
        )
    except Exception:  # noqa: BLE001 — telemetry, never fatal
        log.debug("workspace event publish failed for topic %s", topic, exc_info=True)


def format_ws_sse(event: WorkspaceEvent) -> str:
    """Serialize as a default SSE ``message`` carrying ``{topic, payload}`` so
    the client routes by topic itself (no per-topic ``addEventListener``)."""
    data = json.dumps({"topic": event.topic, "payload": event.payload})
    return f"data: {data}\n\n"
