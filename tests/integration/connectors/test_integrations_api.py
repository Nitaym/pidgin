from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import create_workspace


def test_integrations_catalog(client: TestClient) -> None:
    slug = create_workspace(client, "Integrations Co")
    response = client.get(f"/{slug}/api/integrations/catalog")
    assert response.status_code == 200
    data = response.json()
    types = {entry["connector_type"] for entry in data}
    assert "slack" in types
    assert "gmail" in types


def test_manual_slack_connect_invalid_token(client: TestClient) -> None:
    slug = create_workspace(client, "Slack Co")
    response = client.post(
        f"/{slug}/api/integrations/slack/manual",
        json={
            "display_name": "Dev Slack",
            "fields": {
                "bot_token": "xoxb-invalid",
                "signing_secret": "secret",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["connector_type"] == "slack"
    assert body["health"]["ok"] is False


def test_list_integrations_after_connect(client: TestClient) -> None:
    slug = create_workspace(client, "List Co")
    client.post(
        f"/{slug}/api/integrations/slack/manual",
        json={
            "display_name": "Dev Slack",
            "fields": {"bot_token": "xoxb-invalid", "signing_secret": "secret"},
        },
    )
    listed = client.get(f"/{slug}/api/integrations")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_disconnect_integration(client: TestClient) -> None:
    slug = create_workspace(client, "Disconnect Co")
    created = client.post(
        f"/{slug}/api/integrations/slack/manual",
        json={
            "display_name": "Dev Slack",
            "fields": {"bot_token": "xoxb-invalid", "signing_secret": "secret"},
        },
    )
    installation_id = created.json()["id"]
    deleted = client.delete(f"/{slug}/api/integrations/{installation_id}")
    assert deleted.status_code == 200
    listed = client.get(f"/{slug}/api/integrations")
    assert listed.json() == []
