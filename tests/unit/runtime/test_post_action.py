from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from pidgin.db import apply_migrations, connect
from pidgin.db.connectors import create_installation
from pidgin.runtime.actions import execute_action
from pidgin.types import ActionType, ProposedAction, TrustLabel
from tests.slack_fakes import FakeWebClient


@pytest.fixture(autouse=True)
def fake_slack(monkeypatch: pytest.MonkeyPatch) -> type[FakeWebClient]:
    import slack_sdk

    FakeWebClient.reset()
    monkeypatch.setattr(slack_sdk, "WebClient", FakeWebClient)
    return FakeWebClient


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db = connect(tmp_path / "db.sqlite")
    apply_migrations(db)
    create_installation(
        db,
        connector_type="slack",
        display_name="Slack",
        credentials_json={"auth_mode": "manual", "fields": {"bot_token": "xoxb-test"}},
        config_json={"team_id": "T123"},
    )
    return db


def _action_ctx(conn: sqlite3.Connection) -> SimpleNamespace:
    """Minimal stand-in — _execute_post reads workspace.db_bridge, agent
    identity fields, and event.trust_label."""
    return SimpleNamespace(
        workspace=SimpleNamespace(db_bridge=conn),
        agent=SimpleNamespace(
            agent_id="agent1",
            agent_principal_id="p1",
            display_name="Sam",
            role_title="Support Specialist",
        ),
        event=SimpleNamespace(trust_label=TrustLabel.INTERNAL_AUTHENTICATED),
        turn=SimpleNamespace(id="turn1"),
        egress=None,
        invocation_id=None,
    )


def _post(conn: sqlite3.Connection, target: str, text: str = "Launch is on track.") -> str:
    action = ProposedAction(action_type=ActionType.POST, params={"target": target, "text": text})
    return execute_action(_action_ctx(conn), action)  # type: ignore[arg-type]


def test_post_to_channel_uri(conn: sqlite3.Connection) -> None:
    result = _post(conn, "slack:channel/C0123")
    assert result.startswith("Posted to slack:channel/C0123")
    posts = FakeWebClient.calls_named("chat_postMessage")
    assert len(posts) == 1
    assert posts[0]["channel"] == "C0123"
    assert posts[0]["text"].startswith("Sam · Support Specialist via Pidgin")
    assert "Launch is on track." in posts[0]["text"]


def test_post_dm_by_email(conn: sqlite3.Connection) -> None:
    result = _post(conn, "dana@example.com")
    assert result.startswith("Posted to slack:user/")
    assert FakeWebClient.calls_named("conversations_open") == [{"users": "U777"}]
    posts = FakeWebClient.calls_named("chat_postMessage")
    assert posts[0]["channel"] == "D-U777"


def test_post_to_channel_name(conn: sqlite3.Connection) -> None:
    result = _post(conn, "#general")
    assert result.startswith("Posted to")
    posts = FakeWebClient.calls_named("chat_postMessage")
    assert posts[0]["channel"] == "CGEN"


def test_post_bad_target_reports_error(conn: sqlite3.Connection) -> None:
    result = _post(conn, "not a real target")
    assert result.startswith("Post failed:")
    assert FakeWebClient.calls_named("chat_postMessage") == []


def test_post_missing_params(conn: sqlite3.Connection) -> None:
    action = ProposedAction(action_type=ActionType.POST, params={"text": "hi"})
    assert execute_action(_action_ctx(conn), action) == "Missing target"  # type: ignore[arg-type]
