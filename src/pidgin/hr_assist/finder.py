"""Candidate finder — HR helps the owner pick a profile from the marketplace.

Distinct from the brief-editing coach in ``coach.py``: this answers "which
candidate fits what I need?" over the bundled catalog. On a real LLM backend the
pre-hired HR agent recommends; otherwise a keyword match keeps it useful and
non-blocking.
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

log = logging.getLogger(__name__)

_RECOMMEND_BLOCK = re.compile(r"```pidgin-candidates\s*\n(.*?)\n```", re.DOTALL)
_STOPWORDS = {
    "a", "an", "the", "i", "we", "need", "want", "someone", "who", "that",
    "can", "to", "for", "help", "me", "with", "and", "looking", "find",
    "good", "at", "is", "of", "my", "our", "please", "would", "like",
}


def _catalog_text(candidates: list[dict[str, Any]]) -> str:
    lines = []
    for c in candidates:
        lines.append(
            f"- {c['template_id']}: {c.get('name', '')} ({c.get('role_title', '')}) — "
            f"{c.get('description', '')}"
        )
    return "\n".join(lines)


def _keyword_match(message: str, candidates: list[dict[str, Any]]) -> list[str]:
    tokens = {
        tok
        for tok in re.findall(r"[a-z0-9]+", message.lower())
        if tok not in _STOPWORDS and len(tok) > 2
    }
    if not tokens:
        return []
    scored: list[tuple[int, str]] = []
    for c in candidates:
        haystack = " ".join(
            str(c.get(k, "")) for k in ("name", "role_title", "description")
        ).lower()
        score = sum(1 for tok in tokens if tok in haystack)
        if score:
            scored.append((score, c["template_id"]))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [template_id for _, template_id in scored[:3]]


def _stub_reply(recommended: list[str], candidates: list[dict[str, Any]]) -> str:
    if not recommended:
        return (
            "Tell me what you need this hire to do — the area (support, marketing, "
            "exec, HR), the main task, and the tone — and I'll point you to a candidate."
        )
    by_id = {c["template_id"]: c for c in candidates}
    names = [by_id[i]["name"] for i in recommended if i in by_id]
    listed = ", ".join(names)
    return f"Based on that, take a look at: {listed}. Open a profile to read the full brief."


def find_candidates(
    conn: sqlite3.Connection,
    *,
    message: str,
    history: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Return (reply_text, recommended_template_ids)."""
    valid_ids = {c["template_id"] for c in candidates}
    agent = get_hr_agent(conn)
    if agent is not None:
        try:
            result = _agent_reply(conn, agent, message, history, candidates, valid_ids)
            if result is not None:
                return result
        except Exception:  # noqa: BLE001 — finder must never break the page
            log.exception("[finder] agent reply failed; falling back to keyword match")

    recommended = _keyword_match(message, candidates)
    return _stub_reply(recommended, candidates), recommended


def _agent_reply(
    conn: sqlite3.Connection,
    agent: dict[str, Any],
    message: str,
    history: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    valid_ids: set[str],
) -> tuple[str, list[str]] | None:
    from pidgin.runtime.scheduler import workspace_context_from_conn

    ctx = workspace_context_from_conn(conn)
    model_ref = effective_model_ref(ctx.llm_config)
    if model_ref.backend == "stub":
        return None

    agent_ctx = ctx.turn_store.load_agent_context(agent["id"])
    persona = render_system_prompt(
        agent_ctx.recipe,
        display_name=agent_ctx.display_name,
        role_title=agent_ctx.role_title,
        customization=agent_ctx.customization,
    )
    instruction = (
        "You are helping the owner pick a candidate profile to hire from this "
        "marketplace catalog. Recommend up to 3 that fit, by name, with one short "
        "reason each. Only recommend from the catalog. After your message, on its "
        "own line, emit a single fenced block of the ids you recommend:\n"
        "```pidgin-candidates\n"
        '{"recommended": ["<template_id>", "..."]}\n'
        "```\n\n"
        f"Catalog:\n{_catalog_text(candidates)}"
    )
    messages = [
        ChatMessage(role="system", content=persona),
        ChatMessage(role="system", content=instruction),
    ]
    for msg in history:
        role = "assistant" if msg.get("role") == "assist" else "user"
        messages.append(ChatMessage(role=role, content=str(msg.get("text", ""))))
    messages.append(ChatMessage(role="user", content=message))

    response = invoke_llm(
        model_ref,
        ModelRequest(messages=messages, tools=[], model_ref=model_ref),
    )
    text = (response.assistant_text or "").strip()
    if not text:
        return None
    return _parse(text, valid_ids)


def _parse(text: str, valid_ids: set[str]) -> tuple[str, list[str]]:
    match = _RECOMMEND_BLOCK.search(text)
    if not match:
        return text.strip(), []
    body = text[: match.start()].strip()
    try:
        raw = json.loads(match.group(1))
    except json.JSONDecodeError:
        return text.strip(), []
    recommended = [
        i for i in raw.get("recommended", []) if isinstance(i, str) and i in valid_ids
    ]
    return (body or text.strip()), recommended
