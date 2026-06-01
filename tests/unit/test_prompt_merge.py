from __future__ import annotations

from pathlib import Path

from pidgin.recipes.loader import load_role_recipe
from pidgin.recipes.prompt import render_system_prompt
from pidgin.types.customization import HireCustomization, JobRequirements


def test_render_system_prompt_appends_customization() -> None:
    recipes_dir = Path(__file__).resolve().parents[2] / "recipes"
    recipe = load_role_recipe(recipes_dir / "support-agent-v0.1.json")
    customization = HireCustomization(
        job_requirements=JobRequirements(mission="Ship great support."),
    )
    prompt = render_system_prompt(
        recipe,
        display_name="Alex",
        customization=customization,
    )
    assert "Alex" in prompt
    assert "Ship great support." in prompt
    assert "Job requirements (operator-defined)" in prompt
