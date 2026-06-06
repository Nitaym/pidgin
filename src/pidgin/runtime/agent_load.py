from __future__ import annotations

from pidgin.db.connection import SYSTEM_EMPLOYEE_ID
from pidgin.recipes import RoleRecipe
from pidgin.recipes.models import RecipePermissions
from pidgin.recipes.permissions import resolve_permission_profile
from pidgin.runtime.context import WorkspaceContext
from pidgin.storage.records import AgentContextRecord, InboundEventRecord
from pidgin.types.customization import HireCustomization

_SYSTEM_RECIPE = RoleRecipe(
    recipe_id="system-stub",
    version="0.0.0",
    display_name="Stub Agent",
    role_title="stub",
    permissions=RecipePermissions(
        can_read=["read", "recall"],
        can_write=["say"],
        requires_approval=[],
        blocked=[],
    ),
    system_prompt_template="You are {{display_name}}, a {{role_title}}.",
)


def effective_agent_id(event: InboundEventRecord) -> str:
    return event.target_ai_employee_id or SYSTEM_EMPLOYEE_ID


def load_agent_for_event(
    ctx: WorkspaceContext,
    event: InboundEventRecord,
) -> AgentContextRecord:
    agent_id = effective_agent_id(event)
    try:
        return ctx.turn_store.load_agent_context(agent_id)
    except ValueError:
        return _system_agent_context(agent_id)


def _system_agent_context(agent_id: str) -> AgentContextRecord:
    return AgentContextRecord(
        agent_id=agent_id,
        display_name="Stub Agent",
        role_title="stub",
        handle="system",
        agent_principal_id="system",
        recipe=_SYSTEM_RECIPE,
        customization=HireCustomization(),
        permission_profile=resolve_permission_profile(_SYSTEM_RECIPE),
    )
