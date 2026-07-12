"""Generate hire-wizard assist replies from the pre-hired HR agent.

The HR agent ships pre-hired with every workspace and backs the "Discuss with
Pidgin" panel. This module renders its persona, asks the configured model, and
parses any `pidgin-suggestion` block it emits into an Apply-to-form payload.

It deliberately falls back (returns ``None``) when there is no HR agent or the
workspace runs the stub LLM backend, so the keyword coach in ``sessions.py``
still answers and hiring never blocks on the assist.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from typing import Any

from pidgin.hire import get_hr_agent
from pidgin.llm import effective_model_ref, invoke_llm
from pidgin.llm.types import ChatMessage, ModelRequest
from pidgin.recipes import render_system_prompt
from pidgin.recipes.models import (
    CustomizableField,
    RoleRecipe,
    effective_customizable_fields,
)
from pidgin.types.customization import HireCustomization

log = logging.getLogger(__name__)

_SUGGESTION_BLOCK = re.compile(r"```pidgin-suggestion\s*\n(.*?)\n```", re.DOTALL)


def _field_value(draft: HireCustomization | None, key: str) -> str:
    """Read a customizable field's current value by its dotted key."""
    if draft is None:
        return ""
    obj: Any = draft
    for part in key.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return ""
    return obj if isinstance(obj, str) else ""


def _coach_instruction(
    draft: HireCustomization | None, fields: list[CustomizableField]
) -> str:
    lines = [
        "You are acting as the hiring coach inside the hire wizard. The owner is "
        "drafting a role brief and wants help tightening it. Keep replies short and "
        "concrete. Only emit a pidgin-suggestion block when you have specific text "
        "to drop into a field.",
        "",
        "To suggest a value, emit a fenced ```pidgin-suggestion block containing "
        'JSON: {\"action\": \"apply\", \"targets\": {\"<field key>\": \"<value>\"}}. '
        'For a note that should be appended rather than overwrite, use '
        '{\"action\": \"append_your_take\", \"targets\": {\"your_take\": \"<note>\"}}.',
        "",
        "Fields you may tune (use the exact key):",
    ]
    for field in fields:
        label = f" ({field.label})" if field.label else ""
        value = _field_value(draft, field.key) or "(empty)"
        line = f"- {field.key}{label}: {value}"
        if field.suggestions:
            line += " — options you may propose: " + "; ".join(field.suggestions)
        lines.append(line)
    if draft is not None and draft.job_requirements.responsibilities:
        joined = "; ".join(draft.job_requirements.responsibilities)
        lines.append(f"- (context) responsibilities: {joined}")
    lines.append(
        '- your_take: use action "append_your_take" to add a note without overwriting.'
    )
    return "\n".join(lines)


def _validate_suggestion(raw: Any, valid_keys: set[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    action = raw.get("action")
    targets = raw.get("targets")
    if not isinstance(targets, dict):
        return None
    if action == "append_your_take":
        note = targets.get("your_take")
        if not isinstance(note, str) or not note.strip():
            return None
        return {"action": "append_your_take", "targets": {"your_take": note}}
    if action == "apply":
        clean = {
            key: value
            for key, value in targets.items()
            if key in valid_keys and isinstance(value, str) and value.strip()
        }
        return {"action": "apply", "targets": clean} if clean else None
    return None


def _parse_reply(text: str, valid_keys: set[str]) -> tuple[str, dict[str, Any] | None]:
    match = _SUGGESTION_BLOCK.search(text)
    if not match:
        return text.strip(), None
    body = text[: match.start()].strip()
    try:
        raw = json.loads(match.group(1))
    except json.JSONDecodeError:
        return text.strip(), None
    suggestion = _validate_suggestion(raw, valid_keys)
    return (body or text.strip()), suggestion


def generate_coach_reply(
    conn: sqlite3.Connection,
    *,
    history: list[dict[str, Any]],
    operator_message: str,
    draft_customization: HireCustomization | None,
    recipe: RoleRecipe | None = None,
) -> tuple[str, dict[str, Any] | None] | None:
    """Reply as the pre-hired HR agent, or ``None`` to signal stub fallback.

    ``recipe`` is the role being hired/edited; its declared customizable fields
    (plus the baseline) drive what the coach may suggest — including alternate
    role titles. When ``None``, only the baseline fields are offered.
    """
    agent = get_hr_agent(conn)
    if agent is None:
        return None
    fields = effective_customizable_fields(recipe)
    valid_keys = {f.key for f in fields}
    try:
        from pidgin.runtime.scheduler import workspace_context_from_conn

        ctx = workspace_context_from_conn(conn)
        model_ref = effective_model_ref(ctx.llm_config)
        if model_ref.backend == "stub":
            return None
        agent_ctx = ctx.turn_store.load_agent_context(agent["id"])
        system_prompt = render_system_prompt(
            agent_ctx.recipe,
            display_name=agent_ctx.display_name,
            role_title=agent_ctx.role_title,
            customization=agent_ctx.customization,
        )
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(
                role="system",
                content=_coach_instruction(draft_customization, fields),
            ),
        ]
        for msg in history:
            role = "assistant" if msg.get("role") == "assist" else "user"
            messages.append(ChatMessage(role=role, content=str(msg.get("body_text", ""))))
        messages.append(ChatMessage(role="user", content=operator_message))

        response = invoke_llm(
            model_ref,
            ModelRequest(messages=messages, tools=[], model_ref=model_ref),
        )
        text = (response.assistant_text or "").strip()
        if not text:
            return None
        return _parse_reply(text, valid_keys)
    except Exception:  # noqa: BLE001 — the coach must never break the wizard
        log.exception("[hr-assist] coach reply failed; falling back to stub")
        return None
