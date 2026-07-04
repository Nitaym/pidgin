from __future__ import annotations

import json
import sqlite3
from typing import Any

from pidgin.util.ids import new_ulid, utc_now_iso

_OPEN = "open"


def create_pending_approval(
    conn: sqlite3.Connection,
    *,
    ai_employee_id: str,
    originating_turn_id: str,
    proposed_action: str,
    proposed_action_params: dict[str, Any],
    trust_label: str,
    requesting_principal_id: str,
    requires_approver_principal_id: str,
    drafted_body: str | None = None,
) -> str:
    approval_id = new_ulid()
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO pending_approvals (
          id, ai_employee_id, originating_turn_id, proposed_action,
          proposed_action_params_json, drafted_body, trust_label,
          requesting_principal_id, requires_approver_principal_id,
          current_status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
        """,
        (
            approval_id,
            ai_employee_id,
            originating_turn_id,
            proposed_action,
            json.dumps(proposed_action_params),
            drafted_body,
            trust_label,
            requesting_principal_id,
            requires_approver_principal_id,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO pending_approvals_status_log (
          id, pending_approval_id, from_status, to_status, actor_principal_id, reason, occurred_at
        ) VALUES (?, ?, NULL, 'open', ?, 'Staged for approval', ?)
        """,
        (new_ulid(), approval_id, requesting_principal_id, now),
    )
    conn.commit()

    from pidgin.realtime import publish_workspace_event

    publish_workspace_event(
        conn, "approval.created", {"approval_id": approval_id, "ai_employee_id": ai_employee_id}
    )
    return approval_id


def get_pending_approval(conn: sqlite3.Connection, approval_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM pending_approvals WHERE id = ?",
        (approval_id,),
    ).fetchone()
    return dict(row) if row else None


def list_pending_approvals(
    conn: sqlite3.Connection, *, status: str | None = _OPEN, limit: int = 50
) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute(
            """
            SELECT * FROM pending_approvals
            WHERE current_status = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM pending_approvals ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def resolve_pending_approval(
    conn: sqlite3.Connection,
    *,
    approval_id: str,
    to_status: str,
    actor_principal_id: str,
    resolution_text: str | None = None,
) -> dict[str, Any] | None:
    """Move an open approval to approved/rejected. Returns None if it's missing
    or already resolved (so callers can't double-execute a staged action)."""
    row = conn.execute(
        "SELECT current_status FROM pending_approvals WHERE id = ?",
        (approval_id,),
    ).fetchone()
    if row is None or row["current_status"] != _OPEN:
        return None
    from_status = row["current_status"]
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE pending_approvals
        SET current_status = ?, resolution_text = ?, resolved_at = ?
        WHERE id = ?
        """,
        (to_status, resolution_text, now, approval_id),
    )
    conn.execute(
        """
        INSERT INTO pending_approvals_status_log (
          id, pending_approval_id, from_status, to_status, actor_principal_id, reason, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (new_ulid(), approval_id, from_status, to_status, actor_principal_id, resolution_text, now),
    )
    conn.commit()

    from pidgin.realtime import publish_workspace_event

    publish_workspace_event(
        conn, "approval.resolved", {"approval_id": approval_id, "status": to_status}
    )
    return get_pending_approval(conn, approval_id)
