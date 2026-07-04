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
from pidgin.db.principals import get_or_create_operator_principal
from pidgin.runtime.actions import ActionContext, build_egress, execute_action
from pidgin.runtime.context import WorkspaceContext
from pidgin.types import ActionType, ProposedAction

log = logging.getLogger(__name__)


class ApprovalError(Exception):
    pass


def list_open_approvals(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return list_pending_approvals(conn, status="open")


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
