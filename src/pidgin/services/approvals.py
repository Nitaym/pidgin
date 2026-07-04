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
    """Approve a staged action: actually run it now, then record what happened.

    This is the piece that was entirely missing before — GateOutcome.STAGED had
    nowhere to go once persisted, so "approve" previously had no effect at all.
    """
    approval, turn_detail, agent = _load_open_approval(conn, workspace, approval_id)

    action = ProposedAction(
        action_type=ActionType(approval["proposed_action"]),
        params=json.loads(approval["proposed_action_params_json"]),
    )
    egress = build_egress(workspace, turn_detail.triggering_event)
    action_ctx = ActionContext(
        workspace=workspace,
        turn=turn_detail.turn,
        event=turn_detail.triggering_event,
        agent=agent,
        egress=egress,
        invocation_id=None,
    )

    try:
        result = execute_action(action_ctx, action)
    except Exception as exc:
        log.error(
            "[approvals] approved action EXECUTION CRASHED — approval_id=%s action=%s error=%s",
            approval_id, action.action_type.value, exc, exc_info=True,
        )
        result = f"Action failed: {exc}"

    actor_id = actor_principal_id or get_or_create_operator_principal(conn)
    resolved = resolve_pending_approval(
        conn,
        approval_id=approval_id,
        to_status="approved",
        actor_principal_id=actor_id,
        resolution_text=result,
    )
    if resolved is None:
        raise ApprovalError("Approval was resolved concurrently by someone else")

    log.info("[approvals] APPROVED — approval_id=%s result=%r", approval_id, result[:200])
    _notify(egress, turn_id=turn_detail.turn.id, text=f"✅ Approved — {result}")
    return resolved


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
