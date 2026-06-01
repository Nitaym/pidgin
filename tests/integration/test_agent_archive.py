"""Archive agent lifecycle."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import create_workspace


@pytest.fixture
def slug(client: TestClient) -> str:
    return create_workspace(client, "Archive Co")


def _hire_executive(client: TestClient, slug: str, *, handle: str, display_name: str) -> None:
    response = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "executive-assistant",
            "display_name": display_name,
            "handle": handle,
        },
    )
    assert response.status_code == 200


def test_archive_agent_sets_offboarded_and_hides_from_team(client: TestClient, slug: str) -> None:
    _hire_executive(client, slug, handle="sam", display_name="Sam")

    archive = client.post(f"/{slug}/api/agents/sam/archive")
    assert archive.status_code == 200
    assert archive.json()["current_status"] == "offboarded"

    team = client.get(f"/{slug}/api/agents").json()
    assert not any(a["handle"] == "sam" for a in team)

    profile = client.get(f"/{slug}/api/agents/sam").json()
    assert profile["current_status"] == "offboarded"


def test_archive_agent_is_idempotent_error(client: TestClient, slug: str) -> None:
    _hire_executive(client, slug, handle="riley", display_name="Riley")
    assert client.post(f"/{slug}/api/agents/riley/archive").status_code == 200

    second = client.post(f"/{slug}/api/agents/riley/archive")
    assert second.status_code == 400
    assert "already archived" in second.json()["detail"]


def test_archive_support_agent_allows_rehire(client: TestClient, slug: str) -> None:
    assert client.post(f"/{slug}/api/hire").status_code == 200
    assert client.post(f"/{slug}/api/agents/support/archive").status_code == 200

    rehire = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "support-agent",
            "display_name": "Support Two",
            "handle": "support-2",
        },
    )
    assert rehire.status_code == 200


def test_archive_unknown_agent_returns_404(client: TestClient, slug: str) -> None:
    response = client.post(f"/{slug}/api/agents/nobody/archive")
    assert response.status_code == 404
