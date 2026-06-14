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
from pidgin.types.customization import HireCustomization

log = logging.getLogger(__name__)

_SUGGESTION_BLOCK = re.compile(r"```pidgin-suggestion\s*\n(.*?)\n```", re.DOTALL)
_VALID_TARGETS = {
    "job_requirements.mission",
    "ideal_candidate.tone",
    "ideal_candidate.decision_framework",
    "ideal_candidate.escalation_rules",
}


def _coach_instruction(draft: HireCustomization | None) -> str:
    lines = [
        "You are acting as the hiring coach inside the hire wizard. The owner is "
        "drafting a role brief and wants help tightening it. Keep replies short and "
        "concrete. Only emit a pidgin-suggestion block when you have specific text "
        "to drop into a field.",
    ]
    if draft is not None:
        job = draft.job_requirements
        ideal = draft.ideal_candidate
        responsibilities = "; ".join(job.responsibilities) if job.responsibilities else "(empty)"
        lines.extend(
            [
                "",
                "Current draft brief:",
                f"- Mission: {job.mission or '(empty)'}",
                f"- Responsibilities: {responsibilities}",
                f"- Ideal candidate tone: {ideal.tone or '(empty)'}",
                f"- Decision framework: {ideal.decision_framework or '(empty)'}",
                f"- Escalation rules: {ideal.escalation_rules or '(empty)'}",
                f"- Your take: {draft.your_take or '(empty)'}",
            ]
        )
    return "\n".join(lines)


def _validate_suggestion(raw: Any) -> dict[str, Any] | None:
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
            if key in _VALID_TARGETS and isinstance(value, str) and value.strip()
        }
        return {"action": "apply", "targets": clean} if clean else None
    return None


def _parse_reply(text: str) -> tuple[str, dict[str, Any] | None]:
    match = _SUGGESTION_BLOCK.search(text)
    if not match:
        return text.strip(), None
    body = text[: match.start()].strip()
    try:
        raw = json.loads(match.group(1))
    except json.JSONDecodeError:
        return text.strip(), None
    suggestion = _validate_suggestion(raw)
    return (body or text.strip()), suggestion


def generate_coach_reply(
    conn: sqlite3.Connection,
    *,
    history: list[dict[str, Any]],
    operator_message: str,
    draft_customization: HireCustomization | None,
) -> tuple[str, dict[str, Any] | None] | None:
    """Reply as the pre-hired HR agent, or ``None`` to signal stub fallback."""
    agent = get_hr_agent(conn)
    if agent is None:
        return None
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
            ChatMessage(role="system", content=_coach_instruction(draft_customization)),
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
        return _parse_reply(text)
    except Exception:  # noqa: BLE001 — the coach must never break the wizard
        log.exception("[hr-assist] coach reply failed; falling back to stub")
        return None
