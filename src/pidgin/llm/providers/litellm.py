from __future__ import annotations

from pidgin.llm.types import ModelRequest, ModelResponse


class LiteLLMProvider:
    """Placeholder — multi-provider routing deferred."""

    def complete(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError("LiteLLM provider is not implemented yet")

    def stream(self, request: ModelRequest):
        raise NotImplementedError("LiteLLM provider is not implemented yet")
        yield  # pragma: no cover

    def estimate_cost_usd_micros(self, model_id: str, usage) -> int | None:
        _ = model_id, usage
        return None
