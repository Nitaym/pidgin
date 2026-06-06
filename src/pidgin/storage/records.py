from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pidgin.recipes import RoleRecipe
from pidgin.types import PermissionProfile, TrustLabel
from pidgin.types.customization import HireCustomization


class InboundEventRecord(BaseModel):
    id: str
    trigger_type: str
    target_ai_employee_id: str | None
    sender_principal_id: str | None
    trust_label: TrustLabel
    payload: dict[str, Any] = Field(default_factory=dict)
    processing_status: str = "pending"


class TurnRecord(BaseModel):
    id: str
    ai_employee_id: str
    conversation_id: str | None = None
    triggering_event_id: str
    current_status: str = "running"
    started_at: str
    ended_at: str | None = None


class AgentContextRecord(BaseModel):
    agent_id: str
    display_name: str
    role_title: str
    handle: str
    agent_principal_id: str
    recipe: RoleRecipe
    customization: HireCustomization
    permission_profile: PermissionProfile
    permission_overrides: dict[str, Any] | None = None


class ConversationMessageRecord(BaseModel):
    id: str
    conversation_id: str
    sender_principal_id: str
    sender_display_name: str
    body_text: str
    created_at: str
    originating_turn_id: str | None = None


class ModelInvocationRecord(BaseModel):
    id: str
    turn_id: str
    sequence_in_turn: int
    provider: str
    model_id: str
    request_messages_json: str
    request_tools_json: str | None
    response_json: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd_micros: int | None = None
    latency_ms: int | None = None
    error_text: str | None = None
    invoked_at: str


class GateAuditRecord(BaseModel):
    id: str
    turn_id: str
    technical_actor: str
    virtual_actor_ai_employee_id: str
    virtual_actor_display_name: str
    virtual_actor_role: str
    requester_principal_id: str
    requester_display_name: str
    trust_label: TrustLabel
    policy_decision: str
    action_type: str
    action_params_json: str
    outcome: str
    model_invocation_id: str | None = None
    occurred_at: str


class TurnDetailRecord(BaseModel):
    turn: TurnRecord
    triggering_event: InboundEventRecord | None
    invocations: list[ModelInvocationRecord] = Field(default_factory=list)
    gate_decisions: list[GateAuditRecord] = Field(default_factory=list)
