from __future__ import annotations

from enum import StrEnum


class TriggerType(StrEnum):
    DIRECT_ADDRESS = "direct_address"
    CHANNEL_ACTIVITY = "channel_activity"
    INBOUND_EXTERNAL = "inbound_external"
    TIMER = "timer"
    WATCHER = "watcher"
    SELF_PROMPT = "self_prompt"
    PEER_DELEGATION = "peer_delegation"
    APPROVAL_RESPONSE = "approval_response"


class ActionType(StrEnum):
    SAY = "say"
    POST = "post"
    READ = "read"
    DRAFT = "draft"
    EXECUTE = "execute"
    OPEN_TASK = "open_task"
    REMEMBER = "remember"
    RECALL = "recall"
    SCHEDULE_SELF = "schedule_self"
    WATCH = "watch"
    DELEGATE = "delegate"
    REQUEST_APPROVAL = "request_approval"
    ESCALATE = "escalate"
    CLOSE = "close"


class TrustLabel(StrEnum):
    INTERNAL_AUTHENTICATED = "internal-authenticated"
    EXTERNAL_VERIFIED = "external-verified"
    EXTERNAL_UNVERIFIED = "external-unverified"
    UNTRUSTED_CONTENT = "untrusted-content"


class PolicyDecision(StrEnum):
    ACCEPTED_AS_INSTRUCTION = "accepted_as_instruction"
    ROUTED_TO_INBOX = "routed_to_inbox"
    QUARANTINED = "quarantined"
    AUTO_APPROVED = "auto_approved"
    AWAITING_HUMAN_APPROVAL = "awaiting_human_approval"
    REFUSED_BY_POLICY = "refused_by_policy"
    BLOCKED = "blocked"


class GateOutcome(StrEnum):
    EXECUTED = "executed"
    STAGED = "staged"
    REFUSED = "refused"
    FAILED = "failed"


class ProcessingStatus(StrEnum):
    PENDING = "pending"
    DISPATCHING = "dispatching"
    DONE = "done"
    FAILED = "failed"
