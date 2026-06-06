from __future__ import annotations

import asyncio
import json
from typing import Any

from pidgin.llm.types import StreamEvent
from pidgin.runtime.context import TurnEventSink


class TurnEventBus:
    """In-process pub/sub for SSE streaming (single-process MVP)."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[StreamEvent | None]] = {}
        self._pending: dict[str, list[StreamEvent | None]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def register(self, stream_key: str) -> asyncio.Queue[StreamEvent | None]:
        if stream_key not in self._queues:
            self._queues[stream_key] = asyncio.Queue()
        queue = self._queues[stream_key]
        for event in self._pending.pop(stream_key, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        return queue

    def _put_sync(self, stream_key: str, event: StreamEvent | None) -> None:
        queue = self._queues.get(stream_key)
        if queue is None:
            self._pending.setdefault(stream_key, []).append(event)
            return
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    def _put(self, stream_key: str, event: StreamEvent | None) -> None:
        loop = self._loop
        if loop is not None:
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not loop:
                loop.call_soon_threadsafe(self._put_sync, stream_key, event)
                return
        self._put_sync(stream_key, event)

    def close(self, stream_key: str) -> None:
        self._put(stream_key, None)
        self._pending.pop(stream_key, None)


class KeyedTurnEventSink(TurnEventSink):
    def __init__(self, bus: TurnEventBus, stream_key: str) -> None:
        self._bus = bus
        self._stream_key = stream_key

    def emit(self, event: StreamEvent) -> None:
        self._bus._put(self._stream_key, event)
        if event.turn_id and event.turn_id != self._stream_key:
            self._bus._put(event.turn_id, event)


turn_event_bus = TurnEventBus()


def sse_payload(event: StreamEvent) -> dict[str, Any]:
    data: dict[str, Any] = {"type": event.type}
    if event.delta is not None:
        data["delta"] = event.delta
    if event.action is not None:
        data["action_type"] = event.action.action_type.value
        data["params"] = event.action.params
    if event.usage is not None:
        data["usage"] = event.usage.model_dump()
    if event.error is not None:
        data["message"] = event.error
    if event.response is not None and event.type == "invocation_end":
        data["stop_reason"] = event.response.stop_reason
        if event.turn_id:
            data["turn_id"] = event.turn_id
    return data


def format_sse(event: StreamEvent) -> str:
    payload = json.dumps(sse_payload(event))
    return f"data: {payload}\n\n"
