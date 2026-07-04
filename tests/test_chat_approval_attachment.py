from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from pidgin.connectors.pidgin_chat.connector import PidginChatConnector
from pidgin.connectors.pidgin_chat.ingress import conversation_resource_uri
from pidgin.connectors.types import PrincipalContext, WritePayload
from pidgin.db import apply_migrations, connect
from pidgin.db.approvals import create_pending_approval
from pidgin.db.principals import get_or_create_operator_principal
from pidgin.services.workspace import get_singleton_workspace
from pidgin.types import TrustLabel
from tests.conftest import create_workspace


def test_chat_message_carries_pending_approval_and_status(
    client: TestClient, pidgin_home: Path
) -> None:
    """The inline chat "Approve/Reject" buttons depend on the notice message
    exposing pending_approval_id + its live status. This drives the exact
    write path turn_executor's _stage_action_for_approval uses (egress ->
    PidginChatEgress -> PidginChatConnector.write with extra=...) and confirms
    the attachment round-trips through GET messages, then updates after the
    approval is resolved via the API."""
    slug = create_workspace(client, "Inline Approvals Co")

    hire = client.post(f"/{slug}/api/hire")
    assert hire.status_code == 200
    handle = hire.json()["handle"]

    send = client.post(f"/{slug}/api/agents/{handle}/messages", json={"body": "hello"})
    assert send.status_code == 200
    conversation_id = send.json()["conversation_id"]
    turn_id = send.json()["messages"][-1]["originating_turn_id"]
    assert turn_id

    turns = client.get(f"/{slug}/api/turns").json()
    turn = next(t for t in turns if t["id"] == turn_id)

    workspace = get_singleton_workspace(home=pidgin_home)
    assert workspace is not None
    conn = connect(Path(workspace.path) / "db.sqlite")
    apply_migrations(conn)

    approver_id = get_or_create_operator_principal(conn)
    approval_id = create_pending_approval(
        conn,
        ai_employee_id=turn["ai_employee_id"],
        originating_turn_id=turn_id,
        proposed_action="execute",
        proposed_action_params={
            "resource_uri": "gdrive:folder/root",
            "name": "Docs",
            "kind": "folder",
        },
        trust_label="internal-authenticated",
        requesting_principal_id="operator",
        requires_approver_principal_id=approver_id,
    )

    PidginChatConnector().write(
        conn,
        conversation_resource_uri(conversation_id),
        WritePayload(
            text="Awaiting approval",
            extra={"originating_turn_id": turn_id, "pending_approval_id": approval_id},
        ),
        principal=PrincipalContext(
            principal_id="agent",
            display_name="Test Agent",
            trust_label=TrustLabel.INTERNAL_AUTHENTICATED,
        ),
        mode="execute",
    )
    conn.close()

    messages = client.get(f"/{slug}/api/agents/{handle}/messages").json()["messages"]
    notice = next(m for m in messages if m["body_text"] == "Awaiting approval")
    assert notice["pending_approval_id"] == approval_id
    assert notice["pending_approval_status"] == "open"

    # Other messages (e.g. the stub's greeting) shouldn't pick up an approval.
    greeting = next(m for m in messages if "Hello!" in m["body_text"])
    assert greeting["pending_approval_id"] is None

    approve = client.post(f"/{slug}/api/approvals/{approval_id}/approve")
    assert approve.status_code == 200

    messages_after = client.get(f"/{slug}/api/agents/{handle}/messages").json()["messages"]
    notice_after = next(m for m in messages_after if m["body_text"] == "Awaiting approval")
    assert notice_after["pending_approval_status"] == "approved"
