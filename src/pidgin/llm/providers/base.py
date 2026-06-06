from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from pidgin.llm.types import ModelRequest, ModelResponse, StreamEvent, TokenUsage


class LLMProvider(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...

    def stream(self, request: ModelRequest) -> Iterator[StreamEvent]: ...

    def estimate_cost_usd_micros(self, model_id: str, usage: TokenUsage) -> int | None: ...
