from __future__ import annotations

import json
from typing import Any

from pidgin.recipes.models import RoleRecipe
from pidgin.types import PermissionProfile


def _merge_action_lists(base: list[str], override: list[str] | None) -> list[str]:
    if override is None:
        return list(base)
    return list(dict.fromkeys(base + override))


def resolve_permission_profile(
    recipe: RoleRecipe,
    overrides: dict[str, Any] | None = None,
) -> PermissionProfile:
    """Merge recipe permissions with optional ai_employees.permission_overrides_json."""
    perms = recipe.permissions
    blocked = set(_merge_action_lists(perms.blocked, (overrides or {}).get("blocked")))
    requires_approval = set(
        _merge_action_lists(perms.requires_approval, (overrides or {}).get("requires_approval"))
    ) - blocked
    can_read = set(_merge_action_lists(perms.can_read, (overrides or {}).get("can_read"))) - blocked
    can_write = (
        set(_merge_action_lists(perms.can_write, (overrides or {}).get("can_write"))) - blocked
    )
    return PermissionProfile(
        can_read=sorted(can_read),
        can_write=sorted(can_write),
        requires_approval=sorted(requires_approval),
        blocked=sorted(blocked),
    )


def parse_permission_overrides(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("permission_overrides_json must be a JSON object")
    return data
