from __future__ import annotations

import json

from pydantic import BaseModel, Field

from pidgin.recipes.models import RoleRecipe, WorkHeartbeat


class JobRequirements(BaseModel):
    mission: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


class IdealCandidate(BaseModel):
    tone: str = ""
    decision_framework: str = ""
    escalation_rules: str = ""


class HireCustomization(BaseModel):
    job_requirements: JobRequirements = Field(default_factory=JobRequirements)
    ideal_candidate: IdealCandidate = Field(default_factory=IdealCandidate)
    your_take: str = ""
    # Persona: "" (unspecified), "female", or "male"
    gender: str = ""
    # Voice preset key from pidgin.voice.catalog ("" → auto-pick by gender)
    voice: str = ""
    # Operator-set job title ("" → use the recipe's role_title). The recipe fixes
    # behavior; the title is positioning the operator chooses at hire.
    role_title: str = ""
    # Operator-set work-heartbeat cadence (None → use the recipe's default). Lets
    # the operator dial an agent's tracking cadence at hire without a recipe edit.
    work_heartbeat: WorkHeartbeat | None = None

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str | None) -> HireCustomization | None:
        if not raw:
            return None
        return cls.model_validate(json.loads(raw))

    @classmethod
    def from_recipe_defaults(cls, recipe: RoleRecipe) -> HireCustomization:
        job = JobRequirements()
        if recipe.default_job_requirements is not None:
            job = JobRequirements.model_validate(
                recipe.default_job_requirements.model_dump()
            )
        ideal = IdealCandidate()
        if recipe.default_ideal_candidate is not None:
            ideal = IdealCandidate.model_validate(
                recipe.default_ideal_candidate.model_dump()
            )
        return cls(job_requirements=job, ideal_candidate=ideal)
