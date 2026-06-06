from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pidgin.types.enums import (
    ActionType,
    GateOutcome,
    PolicyDecision,
    TriggerType,
    TrustLabel,
)


class PermissionProfile(BaseModel):
    can_read: list[str] = Field(default_factory=list)
    can_write: list[str] = Field(default_factory=list)
    requires_approval: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)


class ProposedAction(BaseModel):
    action_type: ActionType
    params: dict[str, Any] = Field(default_factory=dict)
    target_system: str | None = None
    target_resource: str | None = None


class GateRequest(BaseModel):
    trust_label: TrustLabel
    action: ProposedAction
    permission_profile: PermissionProfile
    is_direct_commander: bool = True
    triggered_by_untrusted_content_only: bool = False


class GateResult(BaseModel):
    outcome: GateOutcome
    policy_decision: PolicyDecision


class InboundEventCreate(BaseModel):
    trigger_type: TriggerType
    target_ai_employee_id: str | None = None
    sender_principal_id: str | None = None
    trust_label: TrustLabel
    payload: dict[str, Any] = Field(default_factory=dict)
    resumes_turn_id: str | None = None
    parent_turn_id: str | None = None
