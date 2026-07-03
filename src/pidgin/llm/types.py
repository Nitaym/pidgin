from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from pidgin.types import ActionType


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    name: str | None = None


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ModelRef(BaseModel):
    backend: Literal["stub", "anthropic", "litellm"]
    model_id: str
    max_output_tokens: int = 1024
    temperature: float | None = None


class ModelRequest(BaseModel):
    messages: list[ChatMessage]
    tools: list[ToolSpec]
    model_ref: ModelRef


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class ParsedAction(BaseModel):
    action_type: ActionType
    params: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str | None = None


class ModelResponse(BaseModel):
    assistant_text: str | None = None
    actions: list[ParsedAction] = Field(default_factory=list)
    stop_reason: Literal["end_turn", "tool_use", "budget", "error"] = "end_turn"
    usage: TokenUsage = Field(default_factory=TokenUsage)
    raw_response: dict[str, Any] = Field(default_factory=dict)
    error_text: str | None = None


class StreamEvent(BaseModel):
    type: Literal[
        "text_delta",
        "tool_call_ready",
        "usage",
        "invocation_end",
        "error",
    ]
    turn_id: str | None = None
    sequence: int | None = None
    delta: str | None = None
    action: ParsedAction | None = None
    usage: TokenUsage | None = None
    response: ModelResponse | None = None
    error: str | None = None


class LlmBudget(BaseModel):
    max_invocations_per_turn: int = 10


class LlmConfig(BaseModel):
    default_backend: Literal["stub", "anthropic", "litellm"] = "stub"
    default_model: str = "claude-haiku-4-5-20251001"
    budgets: LlmBudget = Field(default_factory=LlmBudget)
