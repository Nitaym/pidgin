from __future__ import annotations

import re

from pidgin.recipes.models import RoleRecipe

_TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_system_prompt(
    recipe: RoleRecipe,
    *,
    display_name: str | None = None,
    role_title: str | None = None,
) -> str:
    values = {
        "display_name": display_name or recipe.display_name,
        "role_title": role_title or recipe.role_title,
    }
    template = recipe.system_prompt_template

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return values.get(key, match.group(0))

    return _TEMPLATE_VAR_PATTERN.sub(replace, template)
