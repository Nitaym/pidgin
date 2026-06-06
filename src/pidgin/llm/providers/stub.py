from __future__ import annotations

from collections.abc import Iterator

from pidgin.llm.types import (
    ModelRequest,
    ModelResponse,
    ParsedAction,
    StreamEvent,
    TokenUsage,
)
from pidgin.types import ActionType


class StubLLMProvider:
    """Deterministic provider for tests and offline dev."""

    def complete(self, request: ModelRequest) -> ModelResponse:
        text = _user_text(request)
        reply = _stub_reply(text)
        return ModelResponse(
            assistant_text=reply,
            actions=[
                ParsedAction(
                    action_type=ActionType.SAY,
                    params={"text": reply},
                )
            ],
            stop_reason="tool_use",
            usage=TokenUsage(input_tokens=10, output_tokens=len(reply.split())),
            raw_response={"stub": True},
        )

    def stream(self, request: ModelRequest) -> Iterator[StreamEvent]:
        response = self.complete(request)
        reply = response.actions[0].params.get("text", "") if response.actions else ""
        words = reply.split()
        if not words:
            yield StreamEvent(type="text_delta", delta=reply)
        else:
            for index, word in enumerate(words):
                chunk = word if index == 0 else f" {word}"
                yield StreamEvent(type="text_delta", delta=chunk)
        if response.actions:
            yield StreamEvent(type="tool_call_ready", action=response.actions[0])
        yield StreamEvent(type="usage", usage=response.usage)
        yield StreamEvent(type="invocation_end", response=response)

    def estimate_cost_usd_micros(self, model_id: str, usage: TokenUsage) -> int | None:
        _ = model_id, usage
        return 0


def _user_text(request: ModelRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content.strip()
    return ""


def _stub_reply(user_message: str) -> str:
    if not user_message:
        return "Hi! I'm here to help. What can I look into for you?"
    if user_message.lower() in {"hi", "hello", "hey"}:
        return "Hello! How can I help you today?"
    return f'Thanks for reaching out. I would look into: "{user_message}".'
