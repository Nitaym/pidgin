from __future__ import annotations

from datetime import UTC, datetime

from pidgin.llm.types import ChatMessage
from pidgin.recipes.prompt import render_system_prompt
from pidgin.runtime.context import WorkspaceContext
from pidgin.services.common_instructions import common_instructions_text
from pidgin.storage.records import AgentContextRecord, InboundEventRecord

_COMMON_HEADER = (
    "# Workspace common instructions\n"
    "_These apply to every agent in this workspace; your role and brief below "
    "take precedence on specifics._"
)


def build_system_prompt(
    agent: AgentContextRecord, *, common_instructions: str | None = None
) -> str:
    base = render_system_prompt(
        agent.recipe,
        display_name=agent.display_name,
        role_title=agent.role_title,
        customization=agent.customization,
    )
    parts: list[str] = []
    if common_instructions and common_instructions.strip():
        parts.append(f"{_COMMON_HEADER}\n\n{common_instructions.strip()}")
    parts.append(base.rstrip())
    body = "\n\n---\n\n".join(parts)
    now = datetime.now(UTC).isoformat()
    return f"{body}\n\n---\n**Current time (UTC):** {now}"


def assemble_messages(
    ctx: WorkspaceContext,
    *,
    agent: AgentContextRecord,
    event: InboundEventRecord,
) -> list[ChatMessage]:
    common = common_instructions_text(ctx.paths.root)
    messages: list[ChatMessage] = [
        ChatMessage(
            role="system",
            content=build_system_prompt(agent, common_instructions=common),
        ),
    ]
    conversation_id = event.payload.get("conversation_id")
    if conversation_id:
        history = ctx.conversation_store.list_messages(str(conversation_id), limit=50)
        for row in history:
            role = "user" if row.originating_turn_id is None else "assistant"
            messages.append(ChatMessage(role=role, content=row.body_text))

    user_text = str(
        event.payload.get("message_text") or event.payload.get("message") or ""
    )
    # The triggering message is usually already the last row of persisted
    # history (the chat path inserts it before the turn runs). Only append it
    # when it isn't already there, so the model doesn't see it twice.
    last = messages[-1] if len(messages) > 1 else None
    already_present = (
        last is not None and last.role == "user" and last.content == user_text
    )
    if user_text and not already_present:
        messages.append(ChatMessage(role="user", content=user_text))
    return messages
