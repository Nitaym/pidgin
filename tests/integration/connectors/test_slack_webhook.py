from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from tests.conftest import create_workspace
from tests.slack_fakes import FakeWebClient

SECRET = "test-signing-secret"


@pytest.fixture(autouse=True)
def fake_slack(monkeypatch: pytest.MonkeyPatch) -> type[FakeWebClient]:
    import slack_sdk

    FakeWebClient.reset()
    monkeypatch.setattr(slack_sdk, "WebClient", FakeWebClient)
    return FakeWebClient


def _setup(client: TestClient) -> tuple[str, str]:
    """Workspace + hired agent + manual Slack install. Returns (slug, handle)."""
    slug = create_workspace(client, "Slack Hook Co")
    hire = client.post(f"/{slug}/api/hire")
    assert hire.status_code == 200
    handle = hire.json()["handle"]

    connected = client.post(
        f"/{slug}/api/integrations/slack/manual",
        json={
            "display_name": "Dev Slack",
            "fields": {"bot_token": "xoxb-test", "signing_secret": SECRET},
        },
    )
    assert connected.status_code == 200
    assert connected.json()["health"]["ok"] is True
    # team_id resolved via auth_test and stored for strict webhook routing
    config = json.loads(connected.json()["config_json"])
    assert config["team_id"] == "T123"
    return slug, handle


def _post_event(
    client: TestClient,
    *,
    text: str,
    event_id: str = "Ev0001",
    secret: str = SECRET,
    sign: bool = True,
):
    payload = {
        "type": "event_callback",
        "team_id": "T123",
        "event_id": event_id,
        "event": {
            "type": "app_mention",
            "text": text,
            "user": "U100",
            "channel": "C100",
            "ts": "1718000000.000001",
            "team": "T123",
        },
    }
    body = json.dumps(payload).encode()
    headers = {"content-type": "application/json"}
    if sign:
        ts = str(int(time.time()))
        digest = hmac.new(secret.encode(), f"v0:{ts}:{body.decode()}".encode(), hashlib.sha256)
        headers["X-Slack-Request-Timestamp"] = ts
        headers["X-Slack-Signature"] = f"v0={digest.hexdigest()}"
    return client.post("/hooks/slack/events", content=body, headers=headers)


def _slack_events(client: TestClient, slug: str) -> list[dict]:
    rows = client.get(f"/{slug}/api/events").json()
    return [
        row
        for row in rows
        if json.loads(row.get("payload_json") or "{}").get("connector_type") == "slack"
    ]


def test_webhook_persists_without_running_turn(client: TestClient) -> None:
    slug, handle = _setup(client)
    FakeWebClient.reset()

    response = _post_event(client, text=f"{handle}, where is my order?")
    assert response.status_code == 200

    events = _slack_events(client, slug)
    assert len(events) == 1
    assert events[0]["processing_status"] == "pending"
    # No turn ran inline, so nothing was posted back to Slack yet.
    assert FakeWebClient.calls_named("chat_postMessage") == []


def test_retry_does_not_duplicate(client: TestClient) -> None:
    slug, handle = _setup(client)

    first = _post_event(client, text=f"{handle}, hello", event_id="EvDup")
    second = _post_event(client, text=f"{handle}, hello", event_id="EvDup")
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(_slack_events(client, slug)) == 1


def test_worker_processing_posts_reply(client: TestClient) -> None:
    slug, handle = _setup(client)
    FakeWebClient.reset()

    assert _post_event(client, text=f"{handle}, where is my order?").status_code == 200
    # Stand-in for the background worker's tick.
    processed = client.post(f"/{slug}/api/run-once")
    assert processed.status_code == 200
    assert processed.json()["processed"] == 1

    posts = FakeWebClient.calls_named("chat_postMessage")
    assert len(posts) == 1
    assert posts[0]["channel"] == "C100"
    assert posts[0]["thread_ts"] == "1718000000.000001"
    assert "via Pidgin" in posts[0]["text"]

    events = _slack_events(client, slug)
    assert events[0]["processing_status"] == "done"


def test_bad_signature_rejected(client: TestClient) -> None:
    slug, handle = _setup(client)
    response = _post_event(client, text=f"{handle}, hello", secret="wrong-secret")
    assert response.status_code == 401
    assert _slack_events(client, slug) == []


def test_missing_signature_rejected(client: TestClient) -> None:
    slug, handle = _setup(client)
    response = _post_event(client, text=f"{handle}, hello", sign=False)
    assert response.status_code == 401


def test_unknown_team_rejected(client: TestClient) -> None:
    _setup(client)
    payload = {
        "type": "event_callback",
        "team_id": "T999",
        "event_id": "EvX",
        "event": {"type": "app_mention", "text": "hi", "team": "T999"},
    }
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    digest = hmac.new(SECRET.encode(), f"v0:{ts}:{body.decode()}".encode(), hashlib.sha256)
    response = client.post(
        "/hooks/slack/events",
        content=body,
        headers={
            "content-type": "application/json",
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": f"v0={digest.hexdigest()}",
        },
    )
    assert response.status_code == 404
