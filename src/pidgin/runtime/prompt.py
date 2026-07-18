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

# The pre-hired hiring agent. Its brief tells it to "recommend candidate profiles
# from the marketplace", so it — and only it — is handed the live catalog below.
_HIRING_RECIPE_ID = "hr-onboarding"


def _hiring_catalog_block(agent: AgentContextRecord) -> str:
    """The marketplace templates the owner can hire, injected for the HR agent.

    Without this the hiring agent is told to recommend marketplace profiles but
    has no way to see them, so it either guesses or (correctly) refuses. Scoped
    to the hiring recipe so every other agent's prompt is unaffected. Best-effort:
    a catalog read failure just omits the block rather than breaking the turn.
    """
    if agent.recipe.recipe_id != _HIRING_RECIPE_ID:
        return ""
    from pidgin.recipes.catalog import list_bundled_template_summaries

    try:
        summaries = list_bundled_template_summaries()
    except Exception:  # noqa: BLE001 — catalog is advisory context, never required
        return ""
    if not summaries:
        return ""
    lines = [
        "# Marketplace catalog (hireable roles)",
        "These are the role profiles the owner can hire right now. This is your "
        "authoritative list — when asked what can be hired, answer from it rather "
        "than saying you can't see the marketplace. Some roles are singletons that "
        "may already be filled in this workspace.",
        "",
    ]
    for s in summaries:
        lines.append(
            f"- **{s.get('name', '')}** ({s.get('role_title', '')}) — "
            f"{s.get('description', '')}"
        )
    return "\n".join(lines)


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


def _obligations_block(ctx: WorkspaceContext, agent: AgentContextRecord) -> str:
    """The agent's 'calendar' — pending wake-ups and open tasks — per
    AGENT_RUNTIME_SPEC §4.3. This is what lets a recurring wake-up pick up
    ongoing work instead of re-deriving its job each time."""
    conn = ctx.db_bridge
    if conn is None:
        return ""
    from pidgin.db.tasks import list_open_tasks
    from pidgin.db.timers import list_pending_timers

    lines: list[str] = []
    timers = list_pending_timers(conn, ai_employee_id=agent.agent_id)
    if timers:
        lines.append("My scheduled wake-ups:")
        for t in timers:
            tag = " (recurring)" if t["kind"] == "recurring" else ""
            lines.append(f"  - {t['scheduled_at']}{tag} — {t['reason']}")
    tasks = list_open_tasks(conn, owner_principal_id=agent.agent_principal_id)
    if tasks:
        lines.append("My open tasks:")
        for task in tasks:
            due = f" (due {task['due_at']})" if task["due_at"] else ""
            lines.append(f"  - [{task['current_status']}] {task['title']}{due} (id {task['id']})")
    return "\n".join(lines)


def assemble_messages(
    ctx: WorkspaceContext,
    *,
    agent: AgentContextRecord,
    event: InboundEventRecord,
) -> list[ChatMessage]:
    common = common_instructions_text(ctx.paths.root)
    system_text = build_system_prompt(agent, common_instructions=common)
    catalog = _hiring_catalog_block(agent)
    if catalog:
        system_text = f"{system_text}\n\n---\n{catalog}"
    obligations = _obligations_block(ctx, agent)
    if obligations:
        system_text = f"{system_text}\n\n---\n{obligations}"
    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=system_text),
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
