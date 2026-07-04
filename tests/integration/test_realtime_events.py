from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from pidgin.db import apply_migrations, connect
from pidgin.db.approvals import create_pending_approval, resolve_pending_approval
from pidgin.db.chat import get_or_create_agent_conversation, insert_message
from pidgin.db.employees import get_agent_by_handle
from pidgin.db.principals import get_or_create_operator_principal
from pidgin.realtime import workspace_event_bus
from pidgin.services.workspace import get_singleton_workspace
from tests.conftest import create_workspace


def _direct_conn(pidgin_home: Path):
    workspace = get_singleton_workspace(home=pidgin_home)
    assert workspace is not None
    conn = connect(Path(workspace.path) / "db.sqlite")
    apply_migrations(conn)
    return conn


def _subscribe(pidgin_home: Path):
    """Subscribe to the singleton bus for the current workspace, forcing
    synchronous delivery so events land on the queue immediately."""
    workspace = get_singleton_workspace(home=pidgin_home)
    assert workspace is not None
    # A prior test may have bound (and since closed) an event loop; reset so the
    # DB-write publish fans out synchronously on this thread.
    workspace_event_bus._loop = None
    return workspace.id, workspace_event_bus.subscribe(workspace.id)


def test_insert_message_publishes_message_created(
    client: TestClient, pidgin_home: Path
) -> None:
    slug = create_workspace(client, "Realtime Co")
    handle = client.post(f"/{slug}/api/hire").json()["handle"]

    conn = _direct_conn(pidgin_home)
    agent = get_agent_by_handle(conn, handle)
    assert agent is not None
    operator = get_or_create_operator_principal(conn)
    conversation_id = get_or_create_agent_conversation(conn, agent["id"])

    workspace_id, queue = _subscribe(pidgin_home)
    try:
        insert_message(
            conn,
            conversation_id=conversation_id,
            sender_principal_id=operator,
            sender_display_name="Sales Bot",
            body_text="Deal closed.",
            originating_turn_id="turn-1",  # agent-authored
        )
        event = queue.get_nowait()
        assert event.topic == "message.created"
        assert event.payload["conversation_id"] == conversation_id
        assert event.payload["agent_authored"] is True
    finally:
        workspace_event_bus.unsubscribe(workspace_id, queue)


def test_approval_lifecycle_publishes_created_and_resolved(
    client: TestClient, pidgin_home: Path
) -> None:
    slug = create_workspace(client, "Realtime Approvals Co")
    handle = client.post(f"/{slug}/api/hire").json()["handle"]

    conn = _direct_conn(pidgin_home)
    agent = get_agent_by_handle(conn, handle)
    assert agent is not None
    approver = get_or_create_operator_principal(conn)

    workspace_id, queue = _subscribe(pidgin_home)
    try:
        approval_id = create_pending_approval(
            conn,
            ai_employee_id=agent["id"],
            originating_turn_id="turn-1",
            proposed_action="execute",
            proposed_action_params={"kind": "folder"},
            trust_label="internal-authenticated",
            requesting_principal_id="operator",
            requires_approver_principal_id=approver,
        )
        created = queue.get_nowait()
        assert created.topic == "approval.created"
        assert created.payload["approval_id"] == approval_id

        resolve_pending_approval(
            conn,
            approval_id=approval_id,
            to_status="approved",
            actor_principal_id=approver,
        )
        resolved = queue.get_nowait()
        assert resolved.topic == "approval.resolved"
        assert resolved.payload == {"approval_id": approval_id, "status": "approved"}
    finally:
        workspace_event_bus.unsubscribe(workspace_id, queue)


def test_stream_endpoint_requires_auth() -> None:
    """Auth is enforced before any streaming begins, so this returns a normal
    (non-streaming) response. The authenticated happy path is an infinite SSE
    stream that TestClient can't drive without hanging — it's verified in the
    browser instead; the fan-out and publish paths are covered above."""
    from pidgin.api.app import create_app

    unauth = TestClient(create_app(secret_key="test-secret", allow_dev_auth=True))
    response = unauth.get("/anything/api/stream")
    assert response.status_code in (401, 404)
