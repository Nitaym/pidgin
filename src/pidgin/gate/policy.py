from __future__ import annotations

from pidgin.types import (
    ActionType,
    GateOutcome,
    GateRequest,
    GateResult,
    PolicyDecision,
    TrustLabel,
)


def gate(request: GateRequest) -> GateResult:
    """Policy gate — runs outside the LLM. MVP: permission profile + trust label checks."""
    action = request.action.action_type.value
    profile = request.permission_profile

    if action in profile.blocked:
        return GateResult(
            outcome=GateOutcome.REFUSED,
            policy_decision=PolicyDecision.REFUSED_BY_POLICY,
        )

    if request.triggered_by_untrusted_content_only and not request.is_direct_commander:
        return GateResult(
            outcome=GateOutcome.REFUSED,
            policy_decision=PolicyDecision.QUARANTINED,
        )

    if request.trust_label == TrustLabel.UNTRUSTED_CONTENT:
        return GateResult(
            outcome=GateOutcome.REFUSED,
            policy_decision=PolicyDecision.QUARANTINED,
        )

    if action in profile.requires_approval:
        return GateResult(
            outcome=GateOutcome.STAGED,
            policy_decision=PolicyDecision.AWAITING_HUMAN_APPROVAL,
        )

    write_actions = {
        ActionType.SAY,
        ActionType.POST,
        ActionType.DRAFT,
        ActionType.EXECUTE,
        ActionType.OPEN_TASK,
        ActionType.REMEMBER,
        ActionType.SCHEDULE_SELF,
        ActionType.WATCH,
        ActionType.DELEGATE,
        ActionType.REQUEST_APPROVAL,
        ActionType.ESCALATE,
        ActionType.CLOSE,
    }
    if request.action.action_type in write_actions:
        allowed = set(profile.can_write)
        if allowed and action not in allowed:
            return GateResult(
                outcome=GateOutcome.REFUSED,
                policy_decision=PolicyDecision.REFUSED_BY_POLICY,
            )

    read_actions = {ActionType.READ, ActionType.RECALL}
    if request.action.action_type in read_actions:
        allowed = set(profile.can_read)
        if allowed and action not in allowed:
            return GateResult(
                outcome=GateOutcome.REFUSED,
                policy_decision=PolicyDecision.REFUSED_BY_POLICY,
            )

    if request.trust_label in (TrustLabel.EXTERNAL_UNVERIFIED, TrustLabel.UNTRUSTED_CONTENT):
        return GateResult(
            outcome=GateOutcome.STAGED,
            policy_decision=PolicyDecision.ROUTED_TO_INBOX,
        )

    return GateResult(
        outcome=GateOutcome.EXECUTED,
        policy_decision=PolicyDecision.ACCEPTED_AS_INSTRUCTION,
    )
