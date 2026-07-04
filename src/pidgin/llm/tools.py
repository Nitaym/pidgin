from __future__ import annotations

from pidgin.llm.types import ToolSpec
from pidgin.types import PermissionProfile


def tools_for_profile(profile: PermissionProfile) -> list[ToolSpec]:
    # requires_approval actions (e.g. "execute" gated behind owner approval) are
    # allowed by gate.py independently of can_write — they must be offered as
    # tools too, or the agent can never even attempt them to get staged.
    allowed = set(profile.can_read) | set(profile.can_write) | set(profile.requires_approval)
    blocked = set(profile.blocked)
    names = sorted(action for action in allowed - blocked if action in _TOOL_DEFS)
    return [_TOOL_DEFS[name] for name in names]


_TOOL_DEFS: dict[str, ToolSpec] = {
    "say": ToolSpec(
        name="say",
        description="Send a reply message to the user in the current conversation.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Message body"}},
            "required": ["text"],
        },
    ),
    "post": ToolSpec(
        name="post",
        description=(
            "Proactively send a message to a person or channel, independent of "
            "the current conversation. Use this to reach out — e.g. DM someone "
            "on Slack or post to a channel. Target forms: a resource URI "
            "(slack:channel/C0123, slack:user/U0123), an email address, or a "
            "#channel-name."
        ),
        parameters={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Destination: resource URI, email address, or #channel-name",
                },
                "text": {"type": "string", "description": "Message body"},
            },
            "required": ["target", "text"],
        },
    ),
    "read": ToolSpec(
        name="read",
        description="Read content from a connector resource URI.",
        parameters={
            "type": "object",
            "properties": {
                "resource_uri": {"type": "string", "description": "Pidgin resource URI"},
            },
            "required": ["resource_uri"],
        },
    ),
    "execute": ToolSpec(
        name="execute",
        description=(
            "Create new content in a connector resource — e.g. add a document to "
            "Google Drive. Target the parent folder URI (gdrive:folder/<id>); to "
            "create at the top level of Drive use gdrive:folder/root. Set "
            "`name`, and choose `kind`: use \"doc\" for a real Google Doc (your "
            "markdown content becomes headings/lists), \"folder\" for a subfolder, or "
            "\"file\" for a raw text file. Prefer \"doc\" for anything people will read "
            "in Drive. Creating is additive; editing or deleting existing files is a "
            "separate, owner-approved action and is not done here."
        ),
        parameters={
            "type": "object",
            "properties": {
                "resource_uri": {
                    "type": "string",
                    "description": (
                        "Parent folder to create inside, e.g. gdrive:folder/<id>. "
                        "Use gdrive:folder/root for the top level of Drive."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Body text (markdown) for a doc or file. Omit when creating a folder."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Name of the new doc, file, or folder.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["doc", "folder", "file"],
                    "description": (
                        "What to create: \"doc\" = native Google Doc (recommended for "
                        "readable content), \"folder\" = subfolder, \"file\" = raw text "
                        "file. Defaults to file."
                    ),
                },
            },
            "required": ["resource_uri"],
        },
    ),
    "schedule_self": ToolSpec(
        name="schedule_self",
        description=(
            "Schedule a wake-up for yourself. Use a one-shot delay_minutes for a "
            "single follow-up, or a recurrence for a standing cadence (e.g. a "
            "daily review or a weekly status report). A recurring wake-up re-arms "
            "itself automatically after each fire — set it once. When it fires you "
            "receive a timer event with your reason and act on it."
        ),
        parameters={
            "type": "object",
            "properties": {
                "delay_minutes": {
                    "type": "number",
                    "description": "One-shot: minutes from now to fire. Omit if using recurrence.",
                },
                "recurrence": {
                    "type": "object",
                    "description": (
                        "Standing cadence. One of: "
                        '{"kind":"daily","at_local_time":"09:00"}, '
                        '{"kind":"weekly","weekday":"fri","at_local_time":"16:00"}, '
                        '{"kind":"interval","every_minutes":240}. Times are UTC.'
                    ),
                    "properties": {
                        "kind": {"type": "string", "enum": ["daily", "weekly", "interval"]},
                        "at_local_time": {"type": "string", "description": "HH:MM (UTC)"},
                        "weekday": {
                            "type": "string",
                            "enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                        },
                        "every_minutes": {"type": "number"},
                    },
                    "required": ["kind"],
                },
                "reason": {
                    "type": "string",
                    "description": "What to do when it fires — be specific, "
                    "future-you only sees this text",
                },
            },
            "required": ["reason"],
        },
    ),
    "open_task": ToolSpec(
        name="open_task",
        description=(
            "Add a durable item to your task backlog — something you're responsible "
            "for that spans more than one turn. Your open tasks are shown to you at "
            "the start of every turn, so this is how you remember ongoing work."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short task title"},
                "description": {"type": "string", "description": "Optional detail"},
                "due_at": {"type": "string", "description": "Optional ISO date/time"},
            },
            "required": ["title"],
        },
    ),
    "close": ToolSpec(
        name="close",
        description=(
            "Update a task on your backlog — mark it done/cancelled, or move it to "
            "in_progress/blocked. Use the task id shown in your open-tasks list."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["in_progress", "blocked", "done", "cancelled"],
                    "description": "Defaults to done",
                },
                "outcome": {"type": "string", "description": "Optional result note"},
            },
            "required": ["task_id"],
        },
    ),
    "escalate": ToolSpec(
        name="escalate",
        description=(
            "Hand something up to your human operator/manager: a decision you need, "
            "a blocker, or a periodic status report. It posts to your chat with them "
            "even if this turn started from a timer with no conversation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What you're escalating, with context"},
            },
            "required": ["text"],
        },
    ),
    "remember": ToolSpec(
        name="remember",
        description="Append a note to the agent's long-term journal memory.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    ),
    "recall": ToolSpec(
        name="recall",
        description="Search the agent's journal memory for relevant notes.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
}
