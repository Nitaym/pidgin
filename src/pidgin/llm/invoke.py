from __future__ import annotations

from pidgin.llm.registry import get_provider
from pidgin.llm.types import ModelRef, ModelRequest, ModelResponse


def invoke_llm(model_ref: ModelRef, request: ModelRequest) -> ModelResponse:
    provider = get_provider(model_ref.backend)
    return provider.complete(request)
