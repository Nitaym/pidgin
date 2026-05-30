from __future__ import annotations

from dataclasses import dataclass

from pidgin.recipes import RoleRecipe, render_system_prompt


@dataclass(frozen=True)
class StubReply:
    text: str
    action_type: str = "say"


def stub_chat_reply(
    *,
    recipe: RoleRecipe,
    agent_display_name: str,
    user_message: str,
) -> StubReply:
    _ = render_system_prompt(recipe, display_name=agent_display_name)
    trimmed = user_message.strip()
    if not trimmed:
        reply = (
            f"Hi, I'm {agent_display_name}. I'm here to help with customer questions. "
            "What can I look into for you?"
        )
    elif trimmed.lower() in {"hi", "hello", "hey"}:
        reply = (
            f"Hello! I'm {agent_display_name}, your {recipe.role_title}. "
            "How can I help you today?"
        )
    else:
        reply = (
            f"Thanks for reaching out. As {agent_display_name}, I'd look into: "
            f'"{trimmed}". '
            "For MVP I'm a stub — a real model will draft a full response here."
        )
    return StubReply(text=reply)
