from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from pidgin.db.approvals import (
    get_pending_approval,
    list_pending_approvals,
    resolve_pending_approval,
)
from pidgin.db.chat import get_or_create_agent_conversation
from pidgin.db.principals import get_or_create_operator_principal
from pidgin.runtime.actions import ActionContext, build_egress, execute_action
from pidgin.runtime.context import WorkspaceContext
from pidgin.types import ActionType, ProposedAction

log = logging.getLogger(__name__)


class ApprovalError(Exception):
    pass


def list_open_approvals(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return list_pending_approvals(conn, status="open")


def build_approval_context(
    conn: sqlite3.Connection,
    workspace: WorkspaceContext,
    approval_id: str,
) -> dict[str, Any]:
    """Assemble the "why" behind a pending approval for the owner to review.

    Bundles: who's asking (the agent + its chat conversation, so the UI can let
    the owner discuss it), the plain-English reason it needs sign-off (derived
    from the gate decision on the originating turn), what triggered the agent in
    the first place, the agent's own rationale (its narrative text that turn),
    and the full ordered step list. Read-only — does NOT resolve the approval.
    """
    approval, turn_detail, agent = _load_open_approval(conn, workspace, approval_id)
    actions = _plan_actions(approval)

    steps = [
        {
            "index": idx,
            "action_type": action.action_type.value,
            "summary": _describe_action(action),
            "params": action.params,
        }
        for idx, action in enumerate(actions, 1)
    ]

    conversation_id = get_or_create_agent_conversation(conn, agent.agent_id)

    # The approval's originating turn is often an internal continuation (an
    # approval_response/timer/self_prompt turn), whose trigger text is machine
    # plumbing — not a reason a human can read. Walk parent_turn_id up the chain
    # to the real request that started this initiative, and grab the agent's own
    # narrative along the way, so the card actually answers "why does it need this?".
    origin = _trace_origin(conn, workspace, turn_detail)

    return {
        "approval_id": approval_id,
        "agent": {
            "id": agent.agent_id,
            "handle": agent.handle,
            "display_name": agent.display_name,
            "role_title": getattr(agent, "role_title", None),
        },
        "conversation_id": conversation_id,
        "why": {
            "policy_reason": _policy_reason(approval, turn_detail, agent, actions),
            "trigger": origin["trigger"],
            "rationale": origin["rationale"],
        },
        "steps": steps,
    }


def _describe_action(action: ProposedAction) -> str:
    """One-line, human-readable summary of a single staged action.

    Mirrors the turn executor's `_describe_staged_action`, kept here so the
    approvals service has no import dependency on the runtime turn code.
    """
    if action.action_type == ActionType.EXECUTE:
        kind = action.params.get("kind") or "file"
        name = action.params.get("name") or "(unnamed)"
        target = action.params.get("resource_uri") or "?"
        return f'create {kind} "{name}" in {target}'
    if action.action_type == ActionType.POST:
        target = action.params.get("resource_uri") or action.params.get("channel") or "a channel"
        return f"post a message to {target}"
    if action.action_type == ActionType.DRAFT:
        return "draft a message for you to review"
    rest = ", ".join(f"{k}: {v}" for k, v in action.params.items())
    return f"{action.action_type.value}{f' — {rest}' if rest else ''}"


def _policy_reason(
    approval: dict[str, Any],
    turn_detail: Any,
    agent: Any,
    actions: list[ProposedAction],
) -> str:
    """Plain-English answer to 'why does this need my approval?'.

    Reads the gate decision recorded for the originating turn: an action lands
    here either because its type is on the agent's always-ask list, or because
    it was triggered by external/unverified content the agent can't act on alone.
    """
    from pidgin.types import PolicyDecision

    name = agent.display_name or f"@{agent.handle}"
    decisions = getattr(turn_detail, "gate_decisions", None) or []
    staged_types = {a.action_type.value for a in actions}
    decision_value = None
    for d in decisions:
        if d.outcome == "staged" and d.action_type in staged_types:
            decision_value = d.policy_decision
            break
    if decision_value is None and decisions:
        decision_value = decisions[-1].policy_decision

    if decision_value == PolicyDecision.AWAITING_HUMAN_APPROVAL.value:
        kinds = ", ".join(sorted(staged_types)) or "this action"
        return (
            f"{name} is allowed to prepare this, but actions of this kind ({kinds}) "
            f"are on its always-ask list — they only run once you approve."
        )
    if decision_value == PolicyDecision.ROUTED_TO_INBOX.value:
        return (
            f"This work was triggered by external or unverified content, so {name} "
            f"needs your sign-off before it acts on it."
        )
    return (
        f"{name} staged this action for your review before it takes effect."
    )


# Triggers that represent a real originating request a human can understand.
# Everything else (approval_response, timer, self_prompt, watcher) is the
# runtime resuming the agent's own work — plumbing, not a reason.
_ROOT_TRIGGERS = {
    "direct_address",
    "inbound_external",
    "channel_activity",
    "peer_delegation",
}


def _trace_origin(
    conn: sqlite3.Connection, workspace: WorkspaceContext, turn_detail: Any
) -> dict[str, Any]:
    """Walk up the turn chain to find the human-readable "why".

    Follows parent_turn_id from the approval's originating turn until it reaches
    the request that actually started this line of work (or the top of an
    autonomous chain), collecting the agent's own narrative on the way. Returns
    {"trigger": {kind, summary}, "rationale": str | None}.
    """
    turn = getattr(turn_detail, "turn", None)
    turn_id = getattr(turn, "id", None)
    rationale: str | None = _rationale_from_detail(turn_detail)
    autonomous_reason: str | None = None
    root: dict[str, Any] | None = None

    seen: set[str] = set()
    hops = 0
    while turn_id and turn_id not in seen and hops < 8:
        seen.add(turn_id)
        hops += 1
        row = conn.execute(
            """
            SELECT e.trigger_type, e.payload_json, e.parent_turn_id
            FROM turns t
            JOIN inbound_events e ON e.id = t.triggering_event_id
            WHERE t.id = ?
            """,
            (turn_id,),
        ).fetchone()
        if row is None:
            break
        trigger_value = row["trigger_type"]
        payload = _loads_dict(row["payload_json"])
        if trigger_value in _ROOT_TRIGGERS:
            root = {"trigger": trigger_value, "payload": payload}
            break
        # Autonomous hop — remember the best reason we pass through, then climb.
        if autonomous_reason is None:
            autonomous_reason = (payload.get("timer_reason") or "").strip() or None
        if rationale is None:
            rationale = _rationale_for_turn(workspace, turn_id)
        parent = row["parent_turn_id"]
        if not parent:
            root = {"trigger": trigger_value, "payload": payload}
            break
        turn_id = parent

    return {
        "trigger": _summarize_origin(root, autonomous_reason),
        "rationale": rationale,
    }


def _summarize_origin(root: dict[str, Any] | None, autonomous_reason: str | None) -> dict[str, Any]:
    if root is None:
        summary = "The agent started this on its own as part of its ongoing work."
        if autonomous_reason:
            summary = f"The agent started this on its own ({autonomous_reason})."
        return {"kind": "autonomous", "summary": summary}

    trigger_value = root["trigger"]
    payload = root["payload"]
    text = (payload.get("message_text") or "").strip()
    sender = payload.get("sender_display_name") or "someone"

    if trigger_value == "direct_address":
        summary = (
            f'{sender} asked: "{_truncate(text)}"' if text else f"{sender} messaged the agent."
        )
    elif trigger_value == "peer_delegation":
        summary = f"Another agent delegated this work.{f' Task: {_truncate(text)}' if text else ''}"
    elif trigger_value in ("inbound_external", "channel_activity"):
        summary = f'Triggered by external activity{f": {_truncate(text)}" if text else ""}.'
    else:
        # An autonomous trigger sitting at the top of the chain (no human root).
        reason = (payload.get("timer_reason") or autonomous_reason or "").strip()
        summary = (
            f"The agent started this on its own ({reason})."
            if reason
            else "The agent started this on its own as part of its ongoing work."
        )
        return {"kind": "autonomous", "summary": summary}

    return {"kind": trigger_value, "summary": summary}


def _rationale_from_detail(turn_detail: Any) -> str | None:
    """The agent's narrative on the approval's own turn, if it wrote any."""
    return _rationale_from_invocations(getattr(turn_detail, "invocations", None) or [])


def _rationale_for_turn(workspace: WorkspaceContext, turn_id: str) -> str | None:
    detail = workspace.turn_store.get_turn_detail(turn_id)
    if detail is None:
        return None
    return _rationale_from_invocations(getattr(detail, "invocations", None) or [])


def _rationale_from_invocations(invocations: list[Any]) -> str | None:
    """Last non-empty assistant text across a turn's model invocations.

    That's where the agent describes, in its own words, what it's doing and why —
    distinct from the injected continuation/plan-notice plumbing.
    """
    for record in reversed(invocations):
        raw = getattr(record, "response_json", None)
        if not raw:
            continue
        response = _loads_dict(raw)
        text = (response.get("assistant_text") or "").strip()
        if text:
            return text
    return None


def _loads_dict(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _truncate(text: str, limit: int = 240) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _truncate(text: str, limit: int = 280) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def approve_pending_approval(
    conn: sqlite3.Connection,
    workspace: WorkspaceContext,
    *,
    approval_id: str,
    actor_principal_id: str | None = None,
) -> dict[str, Any]:
    """Approve a staged plan: run every queued action now, record the outcome,
    then re-dispatch the agent so it continues from where it left off.

    A pending approval holds either a single legacy action or a "plan" (a batch
    of actions staged together in one turn). Approving runs them all in order and
    then enqueues an APPROVAL_RESPONSE continuation turn — that resume step is
    what stops the agent from going silent after each approval.
    """
    approval, turn_detail, agent = _load_open_approval(conn, workspace, approval_id)

    actions = _plan_actions(approval)
    egress = build_egress(workspace, turn_detail.triggering_event)
    action_ctx = ActionContext(
        workspace=workspace,
        turn=turn_detail.turn,
        event=turn_detail.triggering_event,
        agent=agent,
        egress=egress,
        invocation_id=None,
    )

    results: list[str] = []
    for idx, action in enumerate(actions, 1):
        try:
            result = execute_action(action_ctx, action)
        except Exception as exc:
            log.error(
                "[approvals] approved action EXECUTION CRASHED — approval_id=%s "
                "step=%d action=%s error=%s",
                approval_id, idx, action.action_type.value, exc, exc_info=True,
            )
            result = f"Action failed: {exc}"
        results.append(
            f"{idx}. {action.action_type.value}: {result}" if len(actions) > 1 else result
        )
    combined = "\n".join(results)

    actor_id = actor_principal_id or get_or_create_operator_principal(conn)
    resolved = resolve_pending_approval(
        conn,
        approval_id=approval_id,
        to_status="approved",
        actor_principal_id=actor_id,
        resolution_text=combined,
    )
    if resolved is None:
        raise ApprovalError("Approval was resolved concurrently by someone else")

    # Approving the plan opens (or extends) an execution grant so the agent can
    # finish this initiative — dependent creates and edits to its own new work —
    # without asking again. Only edits/deletes of things it did NOT create this
    # session will still stage.
    from pidgin.db.grants import open_execution_grant

    open_execution_grant(
        conn,
        ai_employee_id=agent.agent_id,
        granted_by_principal_id=actor_id,
        origin_approval_id=approval_id,
    )

    log.info(
        "[approvals] APPROVED — approval_id=%s steps=%d result=%r",
        approval_id, len(actions), combined[:200],
    )
    plural = "step" if len(actions) == 1 else "steps"
    _notify(
        egress,
        turn_id=turn_detail.turn.id,
        text=f"✅ Approved — ran {len(actions)} {plural}:\n{combined}",
    )
    _resume_after_approval(
        conn,
        workspace,
        turn_detail=turn_detail,
        agent=agent,
        actor_principal_id=actor_id,
        executed=combined,
    )
    return resolved


def _plan_actions(approval: dict[str, Any]) -> list[ProposedAction]:
    """Unpack an approval into the ordered actions to run.

    A "plan" approval stores {"actions": [{action_type, params}, ...]}; a legacy
    single-action approval stores the action name + its params directly.
    """
    params = json.loads(approval["proposed_action_params_json"])
    if approval["proposed_action"] == "plan":
        return [
            ProposedAction(
                action_type=ActionType(step["action_type"]),
                params=step.get("params", {}),
            )
            for step in params.get("actions", [])
        ]
    return [
        ProposedAction(
            action_type=ActionType(approval["proposed_action"]),
            params=params,
        )
    ]


def _resume_after_approval(
    conn: sqlite3.Connection,
    workspace: WorkspaceContext,
    *,
    turn_detail: Any,
    agent: Any,
    actor_principal_id: str,
    executed: str,
) -> None:
    """Enqueue an APPROVAL_RESPONSE continuation turn and dispatch it.

    The agent wakes with the approved results in hand and continues its plan.
    No infinite-loop risk: any further staged work needs another human approval
    before it can resume again.
    """
    from pidgin.db.events import insert_inbound_event
    from pidgin.runtime.scheduler import run_once
    from pidgin.types import InboundEventCreate, TriggerType

    origin = turn_detail.triggering_event
    if origin is None:
        return
    # Carry the conversation context forward so the continuation's reply lands
    # back where the work was originally requested.
    context_keys = (
        "connector_type",
        "connector_installation_id",
        "external_channel_id",
        "external_thread_id",
        "conversation_id",
        "sender_principal_id",
        "sender_display_name",
    )
    payload = {k: origin.payload[k] for k in context_keys if origin.payload.get(k)}
    payload["message_text"] = (
        "[Approval granted — continue] The owner approved, and I ran the steps you had "
        "queued:\n"
        f"{executed}\n\n"
        "Pick up where you left off and continue with the rest of the plan. If more "
        "steps need approval, queue them the same way and I'll bring them back for sign-off."
    )
    try:
        insert_inbound_event(
            conn,
            InboundEventCreate(
                trigger_type=TriggerType.APPROVAL_RESPONSE,
                target_ai_employee_id=agent.agent_id,
                sender_principal_id=actor_principal_id,
                trust_label=origin.trust_label,
                payload=payload,
                resumes_turn_id=turn_detail.turn.id,
                parent_turn_id=turn_detail.turn.id,
            ),
        )
    except Exception as exc:
        log.warning(
            "[approvals] failed to enqueue continuation — turn_id=%s error=%s",
            turn_detail.turn.id, exc,
        )
        return
    try:
        run_once(conn)
    except Exception as exc:
        log.warning(
            "[approvals] continuation dispatch failed — turn_id=%s error=%s",
            turn_detail.turn.id, exc,
        )


def reject_pending_approval(
    conn: sqlite3.Connection,
    workspace: WorkspaceContext,
    *,
    approval_id: str,
    actor_principal_id: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    _approval, turn_detail, _agent = _load_open_approval(conn, workspace, approval_id)

    actor_id = actor_principal_id or get_or_create_operator_principal(conn)
    resolution_text = reason or "Rejected by owner"
    resolved = resolve_pending_approval(
        conn,
        approval_id=approval_id,
        to_status="rejected",
        actor_principal_id=actor_id,
        resolution_text=resolution_text,
    )
    if resolved is None:
        raise ApprovalError("Approval was resolved concurrently by someone else")

    log.info("[approvals] REJECTED — approval_id=%s reason=%r", approval_id, resolution_text)
    egress = build_egress(workspace, turn_detail.triggering_event)
    outcome_text = f"❌ Not approved — {resolution_text}. No changes were made."
    _notify(egress, turn_id=turn_detail.turn.id, text=outcome_text)
    return resolved


def _load_open_approval(conn: sqlite3.Connection, workspace: WorkspaceContext, approval_id: str):
    approval = get_pending_approval(conn, approval_id)
    if approval is None:
        raise ApprovalError(f"Unknown approval: {approval_id}")
    if approval["current_status"] != "open":
        raise ApprovalError(f"Approval is already {approval['current_status']}")

    turn_detail = workspace.turn_store.get_turn_detail(approval["originating_turn_id"])
    if turn_detail is None or turn_detail.triggering_event is None:
        raise ApprovalError("Originating turn/event is no longer available")

    agent = workspace.turn_store.load_agent_context(approval["ai_employee_id"])
    return approval, turn_detail, agent


def _notify(egress, *, turn_id: str, text: str) -> None:
    try:
        egress.write(text=text, turn_id=turn_id)
    except Exception as exc:
        log.warning("[approvals] failed to post outcome notice — turn_id=%s error=%s", turn_id, exc)
