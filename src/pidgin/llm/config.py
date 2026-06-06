from __future__ import annotations

import json
import os

from pidgin.llm.registry import resolve_backend, resolve_model_ref
from pidgin.llm.types import LlmBudget, LlmConfig, ModelRef


def load_llm_config(settings_json: str | None) -> LlmConfig:
    if not settings_json:
        return LlmConfig()
    try:
        data = json.loads(settings_json)
    except json.JSONDecodeError:
        return LlmConfig()
    llm = data.get("llm")
    if not isinstance(llm, dict):
        return LlmConfig()
    budgets = llm.get("budgets") if isinstance(llm.get("budgets"), dict) else {}
    backend = llm.get("default_backend", "stub")
    if backend not in ("stub", "anthropic", "litellm"):
        backend = "stub"
    return LlmConfig(
        default_backend=backend,
        default_model=str(llm.get("default_model", "claude-sonnet-4-20250514")),
        budgets=LlmBudget(
            max_invocations_per_turn=int(budgets.get("max_invocations_per_turn", 10)),
        ),
    )


def effective_model_ref(config: LlmConfig) -> ModelRef:
    ref = resolve_model_ref(config)
    env_backend = os.environ.get("PIDGIN_LLM_BACKEND", "").strip().lower()
    if env_backend in ("stub", "anthropic", "litellm"):
        ref = ModelRef(backend=env_backend, model_id=ref.model_id)
    if ref.backend == "stub":
        ref = ModelRef(backend="stub", model_id="stub")
    elif resolve_backend(config) == "anthropic" and ref.backend == "anthropic":
        pass
    return ref
