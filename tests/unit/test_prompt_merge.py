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


def test_render_system_prompt_injects_endeavor_and_plan_sheet() -> None:
    recipes_dir = Path(__file__).resolve().parents[2] / "recipes"
    recipe = load_role_recipe(recipes_dir / "operating-partner-v0.1.json")
    customization = HireCustomization(
        endeavor_scope="Ship the v1 launch",
        plan_sheet_uri="gdrive:file/PLAN123",
        role_title="Chief Strategy Officer",
    )
    prompt = render_system_prompt(
        recipe,
        display_name="Sarah",
        role_title="Chief Strategy Officer",
        customization=customization,
    )
    assert "Sarah" in prompt
    assert "Chief Strategy Officer" in prompt  # role_title override flows into the prompt
    assert "Your endeavor and plan (operator-defined)" in prompt
    assert "Ship the v1 launch" in prompt
    assert "gdrive:file/PLAN123" in prompt


def test_render_system_prompt_no_endeavor_section_when_unset() -> None:
    recipes_dir = Path(__file__).resolve().parents[2] / "recipes"
    recipe = load_role_recipe(recipes_dir / "operating-partner-v0.1.json")
    prompt = render_system_prompt(recipe, customization=HireCustomization())
    assert "Your endeavor and plan" not in prompt
