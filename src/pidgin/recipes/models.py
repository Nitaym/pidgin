from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from pidgin.types import ActionType

_RECIPE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
_VALID_ACTIONS = {action.value for action in ActionType}


class DefaultJobRequirements(BaseModel):
    mission: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


class DefaultIdealCandidate(BaseModel):
    tone: str = ""
    decision_framework: str = ""
    escalation_rules: str = ""


class RecipePermissions(BaseModel):
    can_read: list[str] = Field(default_factory=list)
    can_write: list[str] = Field(default_factory=list)
    requires_approval: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)

    @field_validator("can_read", "can_write", "requires_approval", "blocked")
    @classmethod
    def validate_actions(cls, values: list[str]) -> list[str]:
        invalid = [value for value in values if value not in _VALID_ACTIONS]
        if invalid:
            raise ValueError(f"Unknown action type(s): {', '.join(invalid)}")
        return values


class AutonomyLimits(BaseModel):
    max_pending_timers: int | None = None
    max_wakeups_per_day: int | None = None


class SupervisorReport(BaseModel):
    cadence: str = "weekly"  # daily | weekly
    weekday: str = "fri"
    at_local_time: str = "16:00"


class AutonomySettings(BaseModel):
    """How a hired agent runs itself once active (AUTONOMY_SPEC §8).

    Guidance, not hard schedule: the bootstrap turn reads cadence_guidance and
    decides its own wake-ups, so the agent owns its calendar.
    """

    cadence_guidance: list[str] = Field(default_factory=list)
    supervisor_report: SupervisorReport | None = None
    limits: AutonomyLimits | None = None


class RoleRecipe(BaseModel):
    recipe_id: str
    version: str
    display_name: str
    role_title: str
    description: str = ""
    permissions: RecipePermissions
    default_channels: list[str] = Field(default_factory=list)
    system_prompt_template: str
    default_job_requirements: DefaultJobRequirements | None = None
    default_ideal_candidate: DefaultIdealCandidate | None = None
    tools: list[str] = Field(default_factory=list)
    autonomy: AutonomySettings | None = None

    @field_validator("recipe_id")
    @classmethod
    def validate_recipe_id(cls, value: str) -> str:
        if not _RECIPE_ID_PATTERN.match(value):
            raise ValueError("recipe_id must be kebab-case slug")
        return value
