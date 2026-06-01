from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pidgin.api.app import create_app
from pidgin.util.slug import normalize_slug


@pytest.fixture
def pidgin_home(tmp_path: Path) -> Path:
    return tmp_path / ".pidgin"


@pytest.fixture
def client(pidgin_home: Path) -> TestClient:
    app = create_app(
        pidgin_home=pidgin_home,
        secret_key="test-secret",
        allow_dev_auth=True,
    )
    return TestClient(app)


def dev_login(client: TestClient) -> None:
    response = client.post("/api/auth/dev-login", json={})
    assert response.status_code == 200


def create_workspace(
    client: TestClient,
    name: str,
    *,
    slug: str | None = None,
) -> str:
    dev_login(client)
    resolved_slug = slug or normalize_slug(name)
    response = client.post("/api/workspace", json={"name": name, "slug": resolved_slug})
    assert response.status_code == 201
    return response.json()["slug"]
