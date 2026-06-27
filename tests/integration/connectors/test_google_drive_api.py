from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import create_workspace


def test_catalog_lists_google_drive_as_manual(client: TestClient) -> None:
    slug = create_workspace(client, "Drive Co")
    response = client.get(f"/{slug}/api/integrations/catalog")
    assert response.status_code == 200
    entry = next(e for e in response.json() if e["connector_type"] == "google_drive")
    assert entry["auth_modes"] == ["manual"]
    assert "read" in entry["capabilities"]


def test_manual_connect_bad_service_account_is_errored(client: TestClient) -> None:
    # A service account JSON missing private_key fails JWT signing before any
    # network call, so health reports not-ok deterministically.
    slug = create_workspace(client, "Drive Co")
    response = client.post(
        f"/{slug}/api/integrations/google_drive/manual",
        json={
            "display_name": "Acme Drive",
            "fields": {
                "service_account_json": '{"client_email":"svc@acme.iam.gserviceaccount.com"}',
                "delegated_user": "user@acme.com",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["connector_type"] == "google_drive"
    assert body["health"]["ok"] is False


def test_manual_connect_requires_service_account(client: TestClient) -> None:
    slug = create_workspace(client, "Drive Co")
    response = client.post(
        f"/{slug}/api/integrations/google_drive/manual",
        json={"display_name": "Acme Drive", "fields": {"delegated_user": "user@acme.com"}},
    )
    assert response.status_code == 400


def test_delegated_user_visible_in_masked_credentials(client: TestClient) -> None:
    slug = create_workspace(client, "Drive Co")
    created = client.post(
        f"/{slug}/api/integrations/google_drive/manual",
        json={
            "display_name": "Acme Drive",
            "fields": {
                "service_account_json": '{"client_email":"x"}',
                "delegated_user": "user@acme.com",
            },
        },
    )
    fields = created.json()["credentials_masked"]["fields"]
    assert fields["delegated_user"] == "user@acme.com"
    assert fields["service_account_json"] == "***"
