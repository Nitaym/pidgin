from __future__ import annotations

import re

from pidgin.recipes.models import RoleRecipe
from pidgin.types.customization import HireCustomization

_TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_system_prompt(
    recipe: RoleRecipe,
    *,
    display_name: str | None = None,
    role_title: str | None = None,
    customization: HireCustomization | None = None,
) -> str:
    values = {
        "display_name": display_name or recipe.display_name,
        "role_title": role_title or recipe.role_title,
    }
    template = recipe.system_prompt_template

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return values.get(key, match.group(0))

    base = _TEMPLATE_VAR_PATTERN.sub(replace, template)
    if customization is None:
        return base
    appendix = _format_customization_appendix(customization)
    if not appendix:
        return base
    return f"{base.rstrip()}\n\n---\n{appendix}"


def _format_customization_appendix(customization: HireCustomization) -> str:
    sections: list[str] = []
    job = customization.job_requirements
    job_lines: list[str] = []
    if job.mission:
        job_lines.append(f"**Mission:** {job.mission}")
    if job.responsibilities:
        job_lines.append("")
        job_lines.append("**Responsibilities:**")
        job_lines.extend(f"- {item}" for item in job.responsibilities)
    if job.out_of_scope:
        job_lines.append("")
        job_lines.append("**Out of scope:**")
        job_lines.extend(f"- {item}" for item in job.out_of_scope)
    if job_lines:
        sections.append("## Job requirements (operator-defined)\n\n" + "\n".join(job_lines))

    ideal = customization.ideal_candidate
    ideal_lines: list[str] = []
    if ideal.tone:
        ideal_lines.append(f"**Tone:** {ideal.tone}")
    if ideal.decision_framework:
        ideal_lines.append(f"**Decision framework:** {ideal.decision_framework}")
    if ideal.escalation_rules:
        ideal_lines.append(f"**Escalation rules:** {ideal.escalation_rules}")
    if ideal_lines:
        sections.append(
            "## Ideal candidate profile (operator-defined)\n\n" + "\n".join(ideal_lines)
        )

    if customization.your_take.strip():
        sections.append(f"## Your take\n\n{customization.your_take.strip()}")

    return "\n\n".join(sections)
