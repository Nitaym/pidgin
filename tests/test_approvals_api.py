from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from pidgin.db import apply_migrations, connect
from pidgin.db.approvals import create_pending_approval
from pidgin.db.principals import get_or_create_operator_principal
from pidgin.services.workspace import get_singleton_workspace
from tests.conftest import create_workspace


def _direct_conn(pidgin_home: Path):
    workspace = get_singleton_workspace(home=pidgin_home)
    assert workspace is not None
    conn = connect(Path(workspace.path) / "db.sqlite")
    apply_migrations(conn)
    return conn


def _seed_approval(conn, *, ai_employee_id: str, turn_id: str, name: str) -> str:
    approver_id = get_or_create_operator_principal(conn)
    return create_pending_approval(
        conn,
        ai_employee_id=ai_employee_id,
        originating_turn_id=turn_id,
        proposed_action="execute",
        proposed_action_params={
            "resource_uri": "gdrive:folder/root",
            "name": name,
            "kind": "folder",
        },
        trust_label="internal-authenticated",
        requesting_principal_id="operator",
        requires_approver_principal_id=approver_id,
    )


def test_list_approve_reject_approvals(client: TestClient, pidgin_home: Path) -> None:
    """End-to-end check of the approval flow that was entirely missing before:
    GateOutcome.STAGED used to just end the turn with nothing persisted. This
    seeds pending_approvals directly (the way turn_executor's STAGED branch
    now does) and drives the list/approve/reject API the frontend uses."""
    slug = create_workspace(client, "Approvals Test Co")

    hire = client.post(f"/{slug}/api/hire")
    assert hire.status_code == 200
    handle = hire.json()["handle"]

    send = client.post(
        f"/{slug}/api/agents/{handle}/messages",
        json={"body": "hello"},
    )
    assert send.status_code == 200

    turns = client.get(f"/{slug}/api/turns").json()
    assert len(turns) >= 1
    turn = turns[0]

    conn = _direct_conn(pidgin_home)
    approval_id = _seed_approval(
        conn, ai_employee_id=turn["ai_employee_id"], turn_id=turn["id"], name="Approve Me"
    )
    reject_id = _seed_approval(
        conn, ai_employee_id=turn["ai_employee_id"], turn_id=turn["id"], name="Reject Me"
    )
    conn.close()

    listed = client.get(f"/{slug}/api/approvals")
    assert listed.status_code == 200
    ids = {row["id"] for row in listed.json()}
    assert {approval_id, reject_id} <= ids

    approve = client.post(f"/{slug}/api/approvals/{approval_id}/approve")
    assert approve.status_code == 200
    approved = approve.json()
    assert approved["current_status"] == "approved"
    # execute_action ran (against an unconfigured Drive connector in this test
    # env) and its result string — success or failure — was captured.
    assert approved["resolution_text"]

    reject = client.post(
        f"/{slug}/api/approvals/{reject_id}/reject",
        json={"reason": "not now"},
    )
    assert reject.status_code == 200
    rejected = reject.json()
    assert rejected["current_status"] == "rejected"
    assert rejected["resolution_text"] == "not now"

    remaining_ids = {row["id"] for row in client.get(f"/{slug}/api/approvals").json()}
    assert approval_id not in remaining_ids
    assert reject_id not in remaining_ids

    # Resolved approvals can't be resolved again.
    again = client.post(f"/{slug}/api/approvals/{approval_id}/approve")
    assert again.status_code == 400


def test_approve_unknown_approval_404s_cleanly(client: TestClient) -> None:
    slug = create_workspace(client, "Approvals Unknown Co")
    resp = client.post(f"/{slug}/api/approvals/not-a-real-id/approve")
    assert resp.status_code == 400
