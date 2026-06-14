from __future__ import annotations

from pathlib import Path
from typing import Any

from pidgin.recipes.loader import load_role_recipe
from pidgin.recipes.models import RoleRecipe
from pidgin.types.customization import HireCustomization

RECIPES_DIR = Path(__file__).resolve().parents[3] / "recipes"

BUNDLED_RECIPE_FILES: dict[str, str] = {
    "support-agent": "support-agent-v0.1.json",
    "executive-assistant": "executive-assistant-v0.1.json",
    "marketing-agent": "marketing-agent-v0.1.json",
    "marketing-content-writer": "marketing-content-writer-v0.1.json",
    "marketing-campaign-manager": "marketing-campaign-manager-v0.1.json",
    "marketing-social-manager": "marketing-social-manager-v0.1.json",
    "hr-onboarding": "hr-onboarding-v0.1.json",
}


class UnknownRecipeError(Exception):
    pass


def bundled_recipe_path(recipe_id: str) -> Path:
    filename = BUNDLED_RECIPE_FILES.get(recipe_id)
    if filename is None:
        raise UnknownRecipeError(f"Unknown bundled recipe: {recipe_id}")
    path = RECIPES_DIR / filename
    if not path.is_file():
        raise UnknownRecipeError(f"Bundled recipe file missing: {path}")
    return path


def load_bundled_recipe(recipe_id: str) -> RoleRecipe:
    return load_role_recipe(bundled_recipe_path(recipe_id))


def list_bundled_template_summaries() -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for recipe_id in sorted(BUNDLED_RECIPE_FILES):
        recipe = load_bundled_recipe(recipe_id)
        summaries.append(
            {
                "source": "bundled",
                "template_id": recipe_id,
                "name": recipe.display_name,
                "role_title": recipe.role_title,
                "version": recipe.version,
                "description": recipe.description,
            }
        )
    return summaries


def bundled_template_detail(recipe_id: str) -> dict[str, Any]:
    recipe = load_bundled_recipe(recipe_id)
    defaults = HireCustomization.from_recipe_defaults(recipe)
    return {
        "source": "bundled",
        "template_id": recipe_id,
        "name": recipe.display_name,
        "role_title": recipe.role_title,
        "version": recipe.version,
        "description": recipe.description,
        "default_channels": recipe.default_channels,
        "permissions": recipe.permissions.model_dump(),
        "default_job_requirements": defaults.job_requirements.model_dump(),
        "default_ideal_candidate": defaults.ideal_candidate.model_dump(),
    }
