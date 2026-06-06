from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from pidgin.db import apply_migrations, connect
from pidgin.services.workspace import get_singleton_workspace
from tests.conftest import create_workspace


def test_hire_and_chat(client: TestClient) -> None:
    slug = create_workspace(client, "Acme")

    hire = client.post(f"/{slug}/api/hire")
    assert hire.status_code == 200
    handle = hire.json()["handle"]
    conversation_id = hire.json()["conversation_id"]
    assert conversation_id

    send = client.post(
        f"/{slug}/api/agents/{handle}/messages",
        json={"body": "Hi, I need help with my order"},
    )
    assert send.status_code == 200
    messages = send.json()["messages"]
    assert any("I need help with my order" in m["body_text"] for m in messages)
    assert any("Thanks for reaching out" in m["body_text"] for m in messages)


def test_list_role_templates(client: TestClient) -> None:
    slug = create_workspace(client, "Templates Co")
    response = client.get(f"/{slug}/api/role-templates")
    assert response.status_code == 200
    data = response.json()
    assert any(t["template_id"] == "support-agent" for t in data["bundled"])
    assert data["workspace"] == []


def test_hire_with_customization(client: TestClient) -> None:
    slug = create_workspace(client, "Custom Hire Co")
    templates = client.get(f"/{slug}/api/role-templates/bundled/support-agent")
    assert templates.status_code == 200
    defaults = templates.json()

    hire = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "support-agent",
            "display_name": "Alex",
            "handle": "alex",
            "customization": {
                "job_requirements": {
                    "mission": "Help our beta users succeed.",
                    "responsibilities": ["Answer product questions"],
                    "out_of_scope": ["Enterprise contracts"],
                },
                "ideal_candidate": defaults["default_ideal_candidate"],
                "your_take": "Be extra patient with new users.",
            },
        },
    )
    assert hire.status_code == 200
    assert hire.json()["handle"] == "alex"

    brief = client.get(f"/{slug}/api/agents/alex/brief")
    assert brief.status_code == 200
    customization = brief.json()["customization"]
    assert customization["job_requirements"]["mission"] == "Help our beta users succeed."
    assert customization["your_take"] == "Be extra patient with new users."


def test_duplicate_handle_rejected(client: TestClient) -> None:
    slug = create_workspace(client, "Dup Handle Co")
    first = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "executive-assistant",
            "display_name": "Pat",
            "handle": "pat",
        },
    )
    assert first.status_code == 200

    second = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "executive-assistant",
            "display_name": "Patricia",
            "handle": "pat",
        },
    )
    assert second.status_code == 400
    assert "Handle already in use" in second.json()["detail"]


def test_support_singleton_rejected(client: TestClient) -> None:
    slug = create_workspace(client, "Singleton Co")
    first = client.post(f"/{slug}/api/hire")
    assert first.status_code == 200

    second = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "support-agent",
            "display_name": "Support Two",
            "handle": "support-two",
        },
    )
    assert second.status_code == 400
    assert "Support agent is already hired" in second.json()["detail"]


def test_snapshot_immutable_after_customization_edit(
    client: TestClient,
    pidgin_home: Path,
) -> None:
    slug = create_workspace(client, "Snapshot Co")
    hire = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "support-agent",
            "display_name": "Sam",
            "handle": "sam",
            "customization": {
                "job_requirements": {"mission": "Original mission"},
                "ideal_candidate": {},
                "your_take": "",
            },
        },
    )
    assert hire.status_code == 200
    employee_id = hire.json()["ai_employee_id"]

    brief = client.get(f"/{slug}/api/agents/sam/brief").json()
    assert brief["customization"]["job_requirements"]["mission"] == "Original mission"

    workspace = get_singleton_workspace(home=pidgin_home)
    assert workspace is not None
    conn = connect(Path(workspace.path) / "db.sqlite")
    apply_migrations(conn)
    row = conn.execute(
        """
        SELECT s.bundle_json
        FROM ai_employee_recipe_snapshots s
        JOIN ai_employees e ON e.recipe_snapshot_id = s.id
        WHERE e.id = ?
        """,
        (employee_id,),
    ).fetchone()
    conn.close()
    bundle = json.loads(row["bundle_json"])
    assert "Original mission" not in json.dumps(bundle)
