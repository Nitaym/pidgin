from __future__ import annotations

import os
from typing import Literal

from pidgin.llm.providers.base import LLMProvider
from pidgin.llm.providers.stub import StubLLMProvider
from pidgin.llm.types import LlmConfig, ModelRef

Backends = Literal["stub", "anthropic", "litellm"]

_PROVIDERS: dict[str, LLMProvider] = {
    "stub": StubLLMProvider(),
}


def register_provider(backend: str, provider: LLMProvider) -> None:
    _PROVIDERS[backend] = provider


def get_provider(backend: str) -> LLMProvider:
    if backend not in _PROVIDERS:
        raise KeyError(f"Unknown LLM backend: {backend}")
    return _PROVIDERS[backend]


def resolve_backend(config: LlmConfig) -> str:
    env = os.environ.get("PIDGIN_LLM_BACKEND", "").strip().lower()
    if env in ("stub", "anthropic", "litellm"):
        return env
    if config.default_backend != "stub":
        return config.default_backend
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "stub"


def resolve_model_ref(config: LlmConfig) -> ModelRef:
    backend = resolve_backend(config)
    model_id = config.default_model
    if backend == "stub":
        model_id = "stub"
    return ModelRef(backend=backend, model_id=model_id)
