from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from pathlib import Path

import pytest

from pidgin.connectors.slack.ingress import (
    get_signing_secret,
    handle_slack_event,
    parse_agent_directive,
    strip_slack_mentions,
    verify_slack_signature,
)
from pidgin.db import apply_migrations, connect
from pidgin.db.connectors import create_installation, try_record_connector_event
from pidgin.util.ids import new_ulid, utc_now_iso
from tests.slack_fakes import FakeWebClient

SECRET = "test-signing-secret"


def _sign(body: bytes, *, timestamp: str | None = None, secret: str = SECRET) -> tuple[str, str]:
    ts = timestamp or str(int(time.time()))
    digest = hmac.new(secret.encode(), f"v0:{ts}:{body.decode()}".encode(), hashlib.sha256)
    return ts, f"v0={digest.hexdigest()}"


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db = connect(tmp_path / "db.sqlite")
    apply_migrations(db)
    return db


def _insert_agent(conn: sqlite3.Connection, handle: str) -> str:
    agent_id = new_ulid()
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO ai_employees (
          id, display_name, role_title, handle, recipe_snapshot_id,
          human_owner_principal_id, current_status, created_at, updated_at
        ) VALUES (?, ?, 'Tester', ?, 'snap', 'owner', 'active', ?, ?)
        """,
        (agent_id, handle.title(), handle, now, now),
    )
    conn.commit()
    return agent_id


def _slack_installation(conn: sqlite3.Connection, *, config: dict | None = None) -> dict:
    installation_id = create_installation(
        conn,
        connector_type="slack",
        display_name="Slack",
        credentials_json={"auth_mode": "manual", "fields": {"bot_token": "xoxb-test"}},
        config_json=config or {},
    )
    row = conn.execute(
        "SELECT * FROM connector_installations WHERE id = ?", (installation_id,)
    ).fetchone()
    return dict(row)


def _mention_event(text: str, **overrides) -> dict:
    event = {
        "type": "app_mention",
        "text": text,
        "user": "U100",
        "channel": "C100",
        "ts": "1718000000.000001",
        "team": "T123",
    }
    event.update(overrides)
    return event


# --- signature verification ---


def test_verify_signature_valid() -> None:
    body = b'{"hello": "world"}'
    ts, sig = _sign(body)
    assert verify_slack_signature(signing_secret=SECRET, timestamp=ts, body=body, signature=sig)


def test_verify_signature_forged() -> None:
    body = b'{"hello": "world"}'
    ts, _ = _sign(body)
    assert not verify_slack_signature(
        signing_secret=SECRET, timestamp=ts, body=body, signature="v0=deadbeef"
    )


def test_verify_signature_expired() -> None:
    body = b"{}"
    stale = str(int(time.time()) - 600)
    ts, sig = _sign(body, timestamp=stale)
    assert not verify_slack_signature(signing_secret=SECRET, timestamp=ts, body=body, signature=sig)


def test_signing_secret_env_fallback_for_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    installation = {
        "credentials_json": json.dumps({"auth_mode": "oauth2", "access_token": "xoxb-x"})
    }
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
    assert get_signing_secret(installation) is None
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "env-secret")
    assert get_signing_secret(installation) == "env-secret"


def test_signing_secret_manual_takes_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "env-secret")
    installation = {
        "credentials_json": json.dumps(
            {"auth_mode": "manual", "fields": {"signing_secret": "manual-secret"}}
        )
    }
    assert get_signing_secret(installation) == "manual-secret"


# --- directive parsing ---


def test_parse_directive_with_handle() -> None:
    handle, body = parse_agent_directive("<@U0BOT> support, where is my order?")
    assert handle == "support"
    assert body == "where is my order?"


def test_parse_directive_without_handle() -> None:
    handle, body = parse_agent_directive("<@U0BOT> where is my order?")
    assert handle is None
    assert body == "where is my order?"


def test_strip_slack_mentions() -> None:
    assert strip_slack_mentions("<@U0BOT> hello, how are you") == "hello, how are you"


# --- dedup ---


def test_dedup_first_insert_wins(conn: sqlite3.Connection) -> None:
    assert try_record_connector_event(conn, connector_type="slack", external_event_id="Ev1")
    assert not try_record_connector_event(conn, connector_type="slack", external_event_id="Ev1")
    assert try_record_connector_event(conn, connector_type="gmail", external_event_id="Ev1")


def test_handle_slack_event_dedups_retries(conn: sqlite3.Connection) -> None:
    _insert_agent(conn, "support")
    installation = _slack_installation(conn)
    event = _mention_event("support, hello")

    first = handle_slack_event(conn, installation, event, external_event_id="Ev42")
    assert first is not None
    second = handle_slack_event(conn, installation, event, external_event_id="Ev42")
    assert second is None

    count = conn.execute("SELECT COUNT(*) FROM inbound_events").fetchone()[0]
    assert count == 1


# --- routing ---


def test_routes_to_named_agent(conn: sqlite3.Connection) -> None:
    agent_id = _insert_agent(conn, "support")
    installation = _slack_installation(conn)
    event_id = handle_slack_event(conn, installation, _mention_event("support, hi"))
    assert event_id is not None
    row = conn.execute(
        "SELECT target_ai_employee_id, payload_json FROM inbound_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    assert row["target_ai_employee_id"] == agent_id
    assert json.loads(row["payload_json"])["message_text"] == "hi"


def test_unmatched_token_falls_back_to_default_agent(conn: sqlite3.Connection) -> None:
    agent_id = _insert_agent(conn, "support")
    installation = _slack_installation(conn, config={"default_agent_handle": "support"})
    event_id = handle_slack_event(
        conn, installation, _mention_event("<@U0BOT> hello, how are you")
    )
    assert event_id is not None
    row = conn.execute(
        "SELECT target_ai_employee_id, payload_json FROM inbound_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    assert row["target_ai_employee_id"] == agent_id
    # Full message preserved — "hello" was not an agent handle.
    assert json.loads(row["payload_json"])["message_text"] == "hello, how are you"


def test_unknown_agent_posts_hint_instead_of_dropping(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    import slack_sdk

    FakeWebClient.reset()
    monkeypatch.setattr(slack_sdk, "WebClient", FakeWebClient)

    _insert_agent(conn, "support")
    installation = _slack_installation(conn)  # no default agent configured
    event_id = handle_slack_event(conn, installation, _mention_event("hello there"))
    assert event_id is None
    hints = FakeWebClient.calls_named("chat_postMessage")
    assert len(hints) == 1
    assert "support" in hints[0]["text"]


def test_bot_messages_ignored(conn: sqlite3.Connection) -> None:
    _insert_agent(conn, "support")
    installation = _slack_installation(conn)
    event = _mention_event("support, hi", bot_id="B999")
    assert handle_slack_event(conn, installation, event) is None
