from __future__ import annotations

from datetime import UTC, datetime

from pidgin.llm.types import ChatMessage
from pidgin.recipes.prompt import render_system_prompt
from pidgin.runtime.context import WorkspaceContext
from pidgin.storage.records import AgentContextRecord, InboundEventRecord


def build_system_prompt(agent: AgentContextRecord) -> str:
    base = render_system_prompt(
        agent.recipe,
        display_name=agent.display_name,
        role_title=agent.role_title,
        customization=agent.customization,
    )
    now = datetime.now(UTC).isoformat()
    return f"{base.rstrip()}\n\n---\n**Current time (UTC):** {now}"


def assemble_messages(
    ctx: WorkspaceContext,
    *,
    agent: AgentContextRecord,
    event: InboundEventRecord,
) -> list[ChatMessage]:
    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=build_system_prompt(agent)),
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
    if user_text:
        messages.append(ChatMessage(role="user", content=user_text))
    return messages
