from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import create_workspace, dev_login


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_legacy_admin_redirects_to_spa(client: TestClient) -> None:
    root = client.get("/admin", follow_redirects=False)
    assert root.status_code == 308
    assert root.headers["location"] == "/"

    nested = client.get("/admin/workspaces/abc", follow_redirects=False)
    assert nested.status_code == 308
    assert nested.headers["location"] == "/workspaces/abc"


def test_bootstrap_unauthenticated(client: TestClient) -> None:
    response = client.get("/api/bootstrap")
    assert response.status_code == 200
    data = response.json()
    assert data["user"] is None
    assert data["workspace"] is None


def test_admin_human_test_loop(client: TestClient) -> None:
    """Sign in → create workspace → inject → run-once → inspect diagnostics via API."""
    slug = create_workspace(client, "Admin Test Co")

    inject = client.post(
        f"/{slug}/api/inject-event",
        json={"message": "hello from test"},
    )
    assert inject.status_code == 200
    event_id = inject.json()["event_id"]
    assert event_id

    run = client.post(f"/{slug}/api/run-once")
    assert run.status_code == 200
    assert run.json()["processed"] == 1

    events = client.get(f"/{slug}/api/events")
    assert events.status_code == 200
    event_rows = events.json()
    assert len(event_rows) == 1
    assert event_rows[0]["id"] == event_id
    assert event_rows[0]["processing_status"] == "done"

    turns = client.get(f"/{slug}/api/turns")
    assert turns.status_code == 200
    turn_rows = turns.json()
    assert len(turn_rows) == 1
    turn_id = turn_rows[0]["id"]

    detail = client.get(f"/{slug}/api/turns/{turn_id}")
    assert detail.status_code == 200
    assert detail.json()["turn"]["id"] == turn_id
    assert len(detail.json()["audit"]) >= 1

    audit = client.get(f"/{slug}/api/audit")
    assert audit.status_code == 200
    assert len(audit.json()) >= 1


def test_api_create_and_agents(client: TestClient) -> None:
    slug = create_workspace(client, "UI Co")

    agents = client.get(f"/{slug}/api/agents")
    assert agents.status_code == 200
    assert agents.json() == []


def test_workspace_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/api/workspace",
        json={"name": "No Auth Co", "slug": "no-auth-co"},
    )
    assert response.status_code == 401


def test_create_workspace_custom_slug(client: TestClient) -> None:
    slug = create_workspace(client, "Acme Corporation", slug="acme-corp")
    assert slug == "acme-corp"

    bootstrap = client.post("/api/auth/dev-login", json={})
    assert bootstrap.status_code == 200
    data = client.get("/api/bootstrap").json()
    assert data["workspace"]["slug"] == "acme-corp"
    assert data["workspace"]["display_name"] == "Acme Corporation"


def test_create_workspace_rejects_reserved_slug(client: TestClient) -> None:
    dev_login(client)
    response = client.post(
        "/api/workspace",
        json={"name": "Test", "slug": "api"},
    )
    assert response.status_code == 400


def test_dev_login_disabled_by_default(pidgin_home) -> None:
    from pidgin.api.app import create_app

    app = create_app(pidgin_home=pidgin_home, secret_key="test-secret", allow_dev_auth=False)
    client = TestClient(app)
    response = client.post("/api/auth/dev-login", json={})
    assert response.status_code == 404
