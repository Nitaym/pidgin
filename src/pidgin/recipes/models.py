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


class WorkHeartbeat(BaseModel):
    """The recurring work heartbeat an agent arms at bootstrap to advance its
    open-task backlog.

    Absent (``None`` on :class:`AutonomySettings`) preserves the legacy
    30-minute interval every agent used to hardcode. Otherwise the cadence is
    per-recipe (and overridable at hire / after):

    - ``kind = "interval"`` — wake every ``every_minutes`` minutes (the classic
      task-grinding heartbeat).
    - ``kind = "daily"`` — a single change-gated wake at ``at_local_time`` (right
      for a planning role that shouldn't thrash — e.g. the Operating Partner).
    - ``kind = "none"`` — arm no heartbeat at all; the agent leans on its
      guaranteed daily wake floor for liveness.
    """

    kind: str = "interval"  # interval | daily | none
    every_minutes: int | None = 30
    at_local_time: str | None = None

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if value not in {"interval", "daily", "none"}:
            raise ValueError("work_heartbeat.kind must be interval, daily, or none")
        return value


# The heartbeat every agent used before the cadence became configurable. Used
# whenever a recipe declares no work_heartbeat, so existing recipes are unchanged.
DEFAULT_WORK_HEARTBEAT = WorkHeartbeat(kind="interval", every_minutes=30)


class AutonomySettings(BaseModel):
    """How a hired agent runs itself once active (AUTONOMY_SPEC §8).

    Guidance, not hard schedule: the bootstrap turn reads cadence_guidance and
    decides its own wake-ups, so the agent owns its calendar.
    """

    cadence_guidance: list[str] = Field(default_factory=list)
    supervisor_report: SupervisorReport | None = None
    work_heartbeat: WorkHeartbeat | None = None
    limits: AutonomyLimits | None = None


class CustomizableField(BaseModel):
    """A hire-form field the HR coach may help tune.

    ``key`` is a dotted path into :class:`HireCustomization` — either nested
    (``"job_requirements.mission"``) or flat (``"role_title"``, ``"your_take"``).
    ``suggestions`` are optional preset values the coach may offer the operator
    (e.g. alternate role titles for the same recipe).
    """

    key: str
    label: str = ""
    editable: bool = True
    suggestions: list[str] = Field(default_factory=list)


# The fields every hire form has tuned since before recipes could declare their
# own. Kept as the baseline so existing recipes advertise them without change.
DEFAULT_CUSTOMIZABLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("job_requirements.mission", "Mission"),
    ("ideal_candidate.tone", "Ideal candidate tone"),
    ("ideal_candidate.decision_framework", "Decision framework"),
    ("ideal_candidate.escalation_rules", "Escalation rules"),
)


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
    # Fields beyond the baseline this recipe wants the operator to tune at hire
    # (e.g. role_title with alternate-title suggestions). Merged with the
    # baseline by ``effective_customizable_fields``.
    customizable_fields: list[CustomizableField] = Field(default_factory=list)


def effective_customizable_fields(recipe: RoleRecipe | None) -> list[CustomizableField]:
    """The full set of hire-form fields the coach may tune for this recipe:
    the baseline fields plus any extras the recipe declares (deduped by key)."""
    base = [CustomizableField(key=k, label=lbl) for k, lbl in DEFAULT_CUSTOMIZABLE_FIELDS]
    seen = {f.key for f in base}
    extra = [
        f for f in (recipe.customizable_fields if recipe else []) if f.key not in seen
    ]
    return base + extra

    @field_validator("recipe_id")
    @classmethod
    def validate_recipe_id(cls, value: str) -> str:
        if not _RECIPE_ID_PATTERN.match(value):
            raise ValueError("recipe_id must be kebab-case slug")
        return value
