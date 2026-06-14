from __future__ import annotations

from pidgin.llm.types import ToolSpec
from pidgin.types import PermissionProfile


def tools_for_profile(profile: PermissionProfile) -> list[ToolSpec]:
    allowed = set(profile.can_read) | set(profile.can_write)
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
    "schedule_self": ToolSpec(
        name="schedule_self",
        description=(
            "Schedule a future wake-up for yourself to follow up on something. "
            "When it fires you receive a timer event with your reason and can "
            "act on it (e.g. post a message to someone)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "delay_minutes": {
                    "type": "number",
                    "description": "How many minutes from now to fire",
                },
                "reason": {
                    "type": "string",
                    "description": "What to do when the timer fires — be specific, "
                    "future-you only sees this text",
                },
            },
            "required": ["delay_minutes", "reason"],
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
