from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pidgin.recipes.loader import load_role_recipe
from pidgin.recipes.models import RoleRecipe

_RECIPES_DIR = Path(__file__).resolve().parents[2] / "recipes"


@pytest.mark.parametrize(
    "filename",
    ["support-agent-v0.1.json", "executive-assistant-v0.1.json"],
)
def test_bundled_role_recipe_validates(filename: str) -> None:
    data = json.loads((_RECIPES_DIR / filename).read_text(encoding="utf-8"))
    recipe = RoleRecipe.model_validate(data)
    assert recipe.recipe_id
    assert recipe.version


def test_support_agent_has_hire_prefill_defaults() -> None:
    recipe = load_role_recipe(_RECIPES_DIR / "support-agent-v0.1.json")
    assert recipe.default_job_requirements is not None
    assert recipe.default_job_requirements.mission
    assert recipe.default_job_requirements.responsibilities
    assert recipe.default_job_requirements.out_of_scope
    assert recipe.default_ideal_candidate is not None
    assert recipe.default_ideal_candidate.tone
    assert recipe.default_ideal_candidate.decision_framework
    assert recipe.default_ideal_candidate.escalation_rules


def test_invalid_action_rejected() -> None:
    bad = {
        "recipe_id": "bad-recipe",
        "version": "0.1.0",
        "display_name": "Bad",
        "role_title": "Bad",
        "permissions": {"can_read": ["not_an_action"]},
        "system_prompt_template": "Hi",
    }
    with pytest.raises(ValidationError, match="Unknown action"):
        RoleRecipe.model_validate(bad)
