from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import create_workspace


def test_agent_inspect_returns_full_picture(client: TestClient) -> None:
    """The dashboard's inspect endpoint bundles identity, tools, tasks, timers,
    current activity, recent turns/actions, and open approvals for one agent."""
    slug = create_workspace(client, "Dashboard Co")
    handle = client.post(f"/{slug}/api/hire").json()["handle"]

    # A message produces a turn + a logged action.
    client.post(f"/{slug}/api/agents/{handle}/messages", json={"body": "hello"})
    # Activation arms the bootstrap timer and stamps bootstrapped_at.
    activated = client.post(f"/{slug}/api/agents/{handle}/activate")
    assert activated.status_code == 200

    resp = client.get(f"/{slug}/api/agents/{handle}/inspect")
    assert resp.status_code == 200
    data = resp.json()

    assert data["agent"]["handle"] == handle
    assert data["agent"]["current_status"] == "active"
    assert data["agent"]["bootstrapped_at"]
    # Tools reflect the agent's permission profile.
    assert any(tool["name"] == "say" for tool in data["tools"])
    # Activation enqueued at least one timer (the bootstrap wake-up).
    assert len(data["timers"]) >= 1
    # The say action was recorded in the action log.
    assert data["recent_actions"]
    assert data["recent_turns"]
    # Shape is present even when empty.
    assert isinstance(data["tasks"], list)
    assert isinstance(data["open_approvals"], list)
    assert "is_working" in data


def test_agent_inspect_unknown_handle_404s(client: TestClient) -> None:
    slug = create_workspace(client, "Dashboard Missing Co")
    resp = client.get(f"/{slug}/api/agents/nobody/inspect")
    assert resp.status_code == 404


def test_console_invocations_scoped_to_agent(client: TestClient) -> None:
    """The agent console filters model invocations to that one agent."""
    slug = create_workspace(client, "Console Co")
    handle = client.post(f"/{slug}/api/hire").json()["handle"]
    client.post(f"/{slug}/api/agents/{handle}/messages", json={"body": "hello"})

    agent_id = client.get(f"/{slug}/api/agents/{handle}/inspect").json()["agent"]["id"]

    scoped = client.get(f"/{slug}/api/llm-invocations", params={"agent_id": agent_id})
    assert scoped.status_code == 200
    rows = scoped.json()
    assert rows, "the message should have produced an LLM invocation"
    assert all(row["ai_employee_id"] == agent_id for row in rows)
    # Each row carries the input (request messages) and output (response).
    assert rows[0]["request_messages"]
    assert "response" in rows[0]

    empty = client.get(f"/{slug}/api/llm-invocations", params={"agent_id": "no-such-agent"})
    assert empty.json() == []
