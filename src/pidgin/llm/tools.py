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
