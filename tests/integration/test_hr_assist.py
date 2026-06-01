from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from pidgin.services.workspace import get_singleton_workspace
from tests.conftest import create_workspace


def test_hr_assist_session_and_messages(client: TestClient, pidgin_home: Path) -> None:
    slug = create_workspace(client, "HR Assist Co")
    created = client.post(
        f"/{slug}/api/hr-assist/sessions",
        json={"context_type": "hire", "context_id": "draft-hire-1"},
    )
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    sent = client.post(
        f"/{slug}/api/hr-assist/sessions/{session_id}/messages",
        json={"body_text": "Help me write a mission statement"},
    )
    assert sent.status_code == 200
    assert sent.json()["assist_message"]["role"] == "assist"
    assert sent.json()["suggestion"]["action"] == "apply"
    assert "job_requirements.mission" in sent.json()["suggestion"]["targets"]

    listed = client.get(f"/{slug}/api/hr-assist/sessions/{session_id}/messages")
    assert listed.status_code == 200
    assert len(listed.json()["messages"]) == 2

    workspace = get_singleton_workspace(home=pidgin_home)
    assert workspace is not None
    session_dir = Path(workspace.path) / "hr-assist" / "sessions" / session_id
    assert (session_dir / "meta.json").is_file()
    assert (session_dir / "messages.jsonl").is_file()


def test_hire_succeeds_without_hr_assist(client: TestClient) -> None:
    slug = create_workspace(client, "No Assist Co")
    hire = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "executive-assistant",
            "display_name": "Riley",
            "handle": "riley",
        },
    )
    assert hire.status_code == 200


# US-7 aliases for ticket traceability (PID-10)


def test_us7_hr_assist_session_persists_messages(
    client: TestClient,
    pidgin_home: Path,
) -> None:
    test_hr_assist_session_and_messages(client, pidgin_home)


def test_us7_hire_succeeds_without_hr_assist(client: TestClient) -> None:
    test_hire_succeeds_without_hr_assist(client)
