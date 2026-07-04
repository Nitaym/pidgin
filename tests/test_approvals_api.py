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


def _seed_plan_approval(conn, *, ai_employee_id: str, turn_id: str, names: list[str]) -> str:
    approver_id = get_or_create_operator_principal(conn)
    return create_pending_approval(
        conn,
        ai_employee_id=ai_employee_id,
        originating_turn_id=turn_id,
        proposed_action="plan",
        proposed_action_params={
            "actions": [
                {
                    "action_type": "execute",
                    "params": {
                        "resource_uri": "gdrive:folder/root",
                        "name": name,
                        "kind": "folder",
                    },
                }
                for name in names
            ]
        },
        trust_label="internal-authenticated",
        requesting_principal_id="operator",
        requires_approver_principal_id=approver_id,
    )


def test_plan_approval_runs_all_steps_and_resumes(client: TestClient, pidgin_home: Path) -> None:
    """Approving a batched plan runs every queued step, then re-dispatches the
    agent (an approval_response continuation turn) so it picks up where it left
    off instead of going silent after the first approval."""
    slug = create_workspace(client, "Plan Approval Co")
    handle = client.post(f"/{slug}/api/hire").json()["handle"]
    client.post(f"/{slug}/api/agents/{handle}/messages", json={"body": "set up the wiki"})

    turn = client.get(f"/{slug}/api/turns").json()[0]
    turns_before = len(client.get(f"/{slug}/api/turns").json())

    conn = _direct_conn(pidgin_home)
    approval_id = _seed_plan_approval(
        conn,
        ai_employee_id=turn["ai_employee_id"],
        turn_id=turn["id"],
        names=["Company Wiki", "Onboarding"],
    )
    conn.close()

    approved = client.post(f"/{slug}/api/approvals/{approval_id}/approve").json()
    assert approved["current_status"] == "approved"
    # Both queued steps ran and were labelled in the recorded outcome.
    assert "1." in approved["resolution_text"]
    assert "2." in approved["resolution_text"]

    conn = _direct_conn(pidgin_home)
    resume_events = conn.execute(
        "SELECT * FROM inbound_events WHERE trigger_type = 'approval_response'"
        " AND target_ai_employee_id = ?",
        (turn["ai_employee_id"],),
    ).fetchall()
    conn.close()
    assert resume_events, "approval should enqueue a continuation turn"

    # The continuation actually ran, producing at least one more turn.
    turns_after = len(client.get(f"/{slug}/api/turns").json())
    assert turns_after > turns_before


def test_approval_context_explains_why(client: TestClient, pidgin_home: Path) -> None:
    """The context endpoint backs the Approvals page 'why & discuss' panel: it
    surfaces the plain-English policy reason, what triggered the agent, the
    agent's rationale, the full step list, and the conversation id to chat in."""
    slug = create_workspace(client, "Approval Context Co")
    handle = client.post(f"/{slug}/api/hire").json()["handle"]
    client.post(f"/{slug}/api/agents/{handle}/messages", json={"body": "build the wiki"})

    turn = client.get(f"/{slug}/api/turns").json()[0]

    conn = _direct_conn(pidgin_home)
    approval_id = _seed_plan_approval(
        conn,
        ai_employee_id=turn["ai_employee_id"],
        turn_id=turn["id"],
        names=["Company Wiki", "Onboarding"],
    )
    conn.close()

    resp = client.get(f"/{slug}/api/approvals/{approval_id}/context")
    assert resp.status_code == 200
    ctx = resp.json()

    assert ctx["approval_id"] == approval_id
    assert ctx["agent"]["handle"] == handle
    assert ctx["conversation_id"]
    assert ctx["why"]["policy_reason"]
    # The trigger summary should reflect the message that set the agent off.
    assert "build the wiki" in ctx["why"]["trigger"]["summary"]
    # Both staged steps come back, in order, with human-readable summaries.
    assert [s["index"] for s in ctx["steps"]] == [1, 2]
    assert "Company Wiki" in ctx["steps"][0]["summary"]


def test_approval_context_traces_through_continuation(
    client: TestClient, pidgin_home: Path
) -> None:
    """When the approval was staged during an approval_response continuation, the
    'what it's working on' line must trace back to the human request that started
    it — NOT echo the internal '[Approval granted — continue] …' plumbing."""
    from pidgin.db.events import insert_inbound_event
    from pidgin.types import InboundEventCreate, TriggerType, TrustLabel
    from pidgin.util.ids import new_ulid, utc_now_iso

    slug = create_workspace(client, "Approval Trace Co")
    handle = client.post(f"/{slug}/api/hire").json()["handle"]
    client.post(f"/{slug}/api/agents/{handle}/messages", json={"body": "build the onboarding wiki"})

    root_turn = client.get(f"/{slug}/api/turns").json()[0]
    agent_id = root_turn["ai_employee_id"]

    conn = _direct_conn(pidgin_home)
    # Synthesize the continuation event + turn the runtime would create when it
    # resumes the agent after an earlier approval.
    cont_event_id = insert_inbound_event(
        conn,
        InboundEventCreate(
            trigger_type=TriggerType.APPROVAL_RESPONSE,
            target_ai_employee_id=agent_id,
            sender_principal_id="operator",
            trust_label=TrustLabel.INTERNAL_AUTHENTICATED,
            payload={"message_text": "[Approval granted — continue] The owner approved…"},
            parent_turn_id=root_turn["id"],
        ),
    )
    cont_turn_id = new_ulid()
    conn.execute(
        "INSERT INTO turns (id, ai_employee_id, triggering_event_id, parent_turn_id,"
        " current_status, started_at) VALUES (?, ?, ?, ?, 'completed', ?)",
        (cont_turn_id, agent_id, cont_event_id, root_turn["id"], utc_now_iso()),
    )
    conn.commit()
    approval_id = _seed_approval(
        conn, ai_employee_id=agent_id, turn_id=cont_turn_id, name="Gap-Fill"
    )
    conn.close()

    ctx = client.get(f"/{slug}/api/approvals/{approval_id}/context").json()
    summary = ctx["why"]["trigger"]["summary"]
    assert "build the onboarding wiki" in summary
    assert "Approval granted" not in summary
    assert ctx["why"]["trigger"]["kind"] == "direct_address"


def test_approval_context_unknown_404s(client: TestClient) -> None:
    slug = create_workspace(client, "Approval Context Unknown Co")
    resp = client.get(f"/{slug}/api/approvals/not-a-real-id/context")
    assert resp.status_code == 404


def test_audit_log_filters_by_agent(client: TestClient) -> None:
    """The per-agent action log returns only that agent's gate decisions."""
    slug = create_workspace(client, "Audit Filter Co")
    handle = client.post(f"/{slug}/api/hire").json()["handle"]
    client.post(f"/{slug}/api/agents/{handle}/messages", json={"body": "hello"})

    turn = client.get(f"/{slug}/api/turns").json()[0]
    agent_id = turn["ai_employee_id"]

    scoped = client.get(f"/{slug}/api/audit", params={"agent_id": agent_id})
    assert scoped.status_code == 200
    rows = scoped.json()
    assert rows, "the say action should have been logged"
    assert all(row["virtual_actor_ai_employee_id"] == agent_id for row in rows)

    empty = client.get(f"/{slug}/api/audit", params={"agent_id": "no-such-agent"})
    assert empty.json() == []
