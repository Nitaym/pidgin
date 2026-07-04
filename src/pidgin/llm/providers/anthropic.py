from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from typing import Any

from pidgin.llm.parse import parse_tool_call
from pidgin.llm.types import (
    ChatMessage,
    ModelRequest,
    ModelResponse,
    ParsedAction,
    StreamEvent,
    TokenUsage,
    ToolSpec,
)
from pidgin.types import ActionType

log = logging.getLogger(__name__)


def _message_kwargs(request: ModelRequest) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": request.model_ref.model_id,
        "max_tokens": request.model_ref.max_output_tokens,
        "messages": _anthropic_messages(request.messages),
        "system": _system_text(request.messages),
        "tools": _anthropic_tools(request.tools) or None,
    }
    temp = request.model_ref.temperature
    if temp is not None:
        kwargs["temperature"] = temp
    return kwargs


class AnthropicLLMProvider:
    def __init__(self, *, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError("ANTHROPIC_API_KEY is required for anthropic backend")
        from anthropic import Anthropic

        self._client = Anthropic(api_key=key)

    def complete(self, request: ModelRequest) -> ModelResponse:
        started = time.perf_counter()
        try:
            response = self._client.messages.create(**_message_kwargs(request))
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ModelResponse(
                stop_reason="error",
                error_text=str(exc),
                raw_response={"error": str(exc), "latency_ms": latency_ms},
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        return _parse_anthropic_response(response, latency_ms)

    def stream(self, request: ModelRequest) -> Iterator[StreamEvent]:
        started = time.perf_counter()
        tool_name = ""
        tool_args = ""
        text_parts: list[str] = []
        usage = TokenUsage()
        raw_blocks: list[dict[str, Any]] = []

        try:
            with self._client.messages.stream(**_message_kwargs(request)) as stream:
                for event in stream:
                    if event.type == "content_block_delta":
                        delta = event.delta
                        if getattr(delta, "type", None) == "text_delta":
                            piece = delta.text
                            text_parts.append(piece)
                            yield StreamEvent(type="text_delta", delta=piece)
                        elif getattr(delta, "type", None) == "input_json_delta":
                            piece = delta.partial_json
                            tool_args += piece
                            yield StreamEvent(type="text_delta", delta=piece)
                    elif event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            tool_name = block.name
                            tool_args = ""
                    elif event.type == "message_delta":
                        if event.usage:
                            usage.output_tokens = event.usage.output_tokens or usage.output_tokens
                final = stream.get_final_message()
                raw_stop_reason = getattr(final, "stop_reason", None)
                if final.usage:
                    usage = TokenUsage(
                        input_tokens=final.usage.input_tokens,
                        output_tokens=final.usage.output_tokens,
                    )
                raw_blocks = [block.model_dump() for block in final.content]
        except Exception as exc:
            yield StreamEvent(type="error", error=str(exc))
            yield StreamEvent(
                type="invocation_end",
                response=ModelResponse(
                    stop_reason="error",
                    error_text=str(exc),
                    raw_response={"error": str(exc)},
                ),
            )
            return

        latency_ms = int((time.perf_counter() - started) * 1000)
        actions: list[ParsedAction] = []
        if tool_name:
            parsed = parse_tool_call(tool_name, tool_args)
            if parsed:
                actions.append(parsed)
                yield StreamEvent(type="tool_call_ready", action=parsed)
        elif text_parts:
            text = "".join(text_parts)
            action = ParsedAction(action_type=ActionType.SAY, params={"text": text})
            actions.append(action)
            yield StreamEvent(type="tool_call_ready", action=action)

        stop_reason = _resolve_stop_reason(raw_stop_reason, has_actions=bool(actions))
        if stop_reason == "max_tokens":
            _log_truncation(
                tool_name=tool_name,
                partial_args_len=len(tool_args),
                text_len=len("".join(text_parts)),
                output_tokens=usage.output_tokens,
            )

        response = ModelResponse(
            assistant_text="".join(text_parts) or None,
            actions=actions,
            stop_reason=stop_reason,
            usage=usage,
            raw_response={
                "content": raw_blocks,
                "latency_ms": latency_ms,
                "provider_stop_reason": raw_stop_reason,
            },
        )
        yield StreamEvent(type="usage", usage=usage)
        yield StreamEvent(type="invocation_end", response=response)

    def estimate_cost_usd_micros(self, model_id: str, usage: TokenUsage) -> int | None:
        _ = model_id
        # Rough Sonnet pricing placeholder
        input_micros = usage.input_tokens * 3
        output_micros = usage.output_tokens * 15
        return input_micros + output_micros


def _system_text(messages: list[ChatMessage]) -> str | None:
    parts = [m.content for m in messages if m.role == "system"]
    return "\n\n".join(parts) if parts else None


def _anthropic_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            result.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_call_id or "tool",
                            "content": message.content,
                        }
                    ],
                }
            )
        else:
            result.append({"role": message.role, "content": message.content})
    return result


def _anthropic_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters,
        }
        for tool in tools
    ]


def _resolve_stop_reason(raw_stop_reason: str | None, *, has_actions: bool) -> str:
    """Prefer the provider's own stop reason so a max_tokens truncation is never
    silently relabeled as a normal tool_use/end_turn — that mislabeling is what let
    the 2026-07-03 truncated-say incident go undetected until it crashed."""
    if raw_stop_reason == "max_tokens":
        return "max_tokens"
    if raw_stop_reason in ("end_turn", "tool_use"):
        return raw_stop_reason
    return "tool_use" if has_actions else "end_turn"


def _log_truncation(
    *, tool_name: str, partial_args_len: int, text_len: int, output_tokens: int
) -> None:
    log.warning(
        "[llm] response TRUNCATED by max_tokens — tool_in_progress=%s partial_args_len=%d "
        "text_len=%d output_tokens=%d (model ran out of output budget mid-response; "
        "any tool call in progress will have incomplete/missing arguments)",
        tool_name or "(none — cut off before any content)",
        partial_args_len, text_len, output_tokens,
    )


def _parse_anthropic_response(response: Any, latency_ms: int) -> ModelResponse:
    actions: list[ParsedAction] = []
    text_parts: list[str] = []
    tool_name = ""
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_name = block.name
            tool_input = block.input if isinstance(block.input, dict) else {}
            parsed = parse_tool_call(block.name, tool_input)
            if parsed:
                parsed = parsed.model_copy(update={"tool_call_id": block.id})
                actions.append(parsed)

    if not actions and text_parts:
        actions.append(
            ParsedAction(action_type=ActionType.SAY, params={"text": "".join(text_parts)})
        )

    usage = TokenUsage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    raw_stop_reason = getattr(response, "stop_reason", None)
    stop_reason = _resolve_stop_reason(raw_stop_reason, has_actions=bool(actions))
    if stop_reason == "max_tokens":
        _log_truncation(
            tool_name=tool_name,
            partial_args_len=0,
            text_len=len("".join(text_parts)),
            output_tokens=usage.output_tokens,
        )
    return ModelResponse(
        assistant_text="".join(text_parts) or None,
        actions=actions,
        stop_reason=stop_reason,
        usage=usage,
        raw_response={
            "id": response.id,
            "model": response.model,
            "content": [b.model_dump() for b in response.content],
            "latency_ms": latency_ms,
            "provider_stop_reason": raw_stop_reason,
        },
    )
