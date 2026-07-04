from __future__ import annotations

import asyncio
import json
import sqlite3
import threading

from pidgin.realtime import (
    WorkspaceEvent,
    WorkspaceEventBus,
    format_ws_sse,
    publish_workspace_event,
)


def test_fan_out_to_every_subscriber_of_a_workspace() -> None:
    bus = WorkspaceEventBus()
    q1 = bus.subscribe("ws1")
    q2 = bus.subscribe("ws1")
    q_other = bus.subscribe("ws2")

    bus.publish("ws1", WorkspaceEvent("message.created", {"conversation_id": "c1"}))

    assert q1.get_nowait().topic == "message.created"
    assert q2.get_nowait().payload == {"conversation_id": "c1"}
    assert q_other.empty()  # different workspace — not notified


def test_unsubscribe_stops_delivery_and_cleans_up() -> None:
    bus = WorkspaceEventBus()
    q = bus.subscribe("ws1")
    bus.unsubscribe("ws1", q)

    bus.publish("ws1", WorkspaceEvent("x"))

    assert q.empty()
    assert "ws1" not in bus._subscribers  # last subscriber gone → key dropped


def test_full_queue_drops_without_wedging_others() -> None:
    bus = WorkspaceEventBus()
    slow = bus.subscribe("ws1")
    for _ in range(slow.maxsize):
        bus.publish("ws1", WorkspaceEvent("x"))

    # One past capacity must not raise — a wedged client can't break publishing.
    bus.publish("ws1", WorkspaceEvent("overflow"))
    assert slow.qsize() == slow.maxsize


def test_cross_thread_publish_reaches_loop_subscriber() -> None:
    bus = WorkspaceEventBus()
    result: dict[str, str] = {}

    async def main() -> None:
        bus.bind_loop(asyncio.get_running_loop())
        q = bus.subscribe("ws1")
        # Publish from a plain worker thread (no running loop), as the DB
        # write path does — it must marshal onto the bound loop.
        t = threading.Thread(
            target=lambda: bus.publish("ws1", WorkspaceEvent("turn.completed", {"n": 1}))
        )
        t.start()
        t.join()
        event = await asyncio.wait_for(q.get(), timeout=1.0)
        result["topic"] = event.topic

    asyncio.run(main())
    assert result["topic"] == "turn.completed"


def test_publish_workspace_event_derives_id_and_publishes() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE workspace (id TEXT)")
    conn.execute("INSERT INTO workspace (id) VALUES ('ws-42')")

    from pidgin.realtime import workspace_event_bus

    workspace_event_bus._loop = None  # deterministic synchronous delivery
    q = workspace_event_bus.subscribe("ws-42")
    try:
        publish_workspace_event(conn, "message.created", {"conversation_id": "c1"})
        event = q.get_nowait()
        assert event.topic == "message.created"
        assert event.payload["conversation_id"] == "c1"
    finally:
        workspace_event_bus.unsubscribe("ws-42", q)


def test_publish_workspace_event_never_raises() -> None:
    conn = sqlite3.connect(":memory:")  # no workspace table at all
    # A realtime notification must never break the DB write it rides behind.
    publish_workspace_event(conn, "message.created", {})


def test_format_ws_sse_shape() -> None:
    out = format_ws_sse(WorkspaceEvent("approval.resolved", {"status": "approved"}))
    assert out.startswith("data: ")
    assert out.endswith("\n\n")
    body = json.loads(out[len("data: ") :].strip())
    assert body == {"topic": "approval.resolved", "payload": {"status": "approved"}}
