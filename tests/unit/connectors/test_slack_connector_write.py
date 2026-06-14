from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from pidgin.connectors.slack.connector import SlackConnector
from pidgin.connectors.types import PrincipalContext, ResourceUri, WritePayload
from pidgin.types import TrustLabel
from tests.slack_fakes import FakeWebClient

PRINCIPAL = PrincipalContext(
    principal_id="p1",
    display_name="Agent",
    trust_label=TrustLabel.INTERNAL_AUTHENTICATED,
)


@pytest.fixture(autouse=True)
def fake_slack(monkeypatch: pytest.MonkeyPatch) -> type[FakeWebClient]:
    import slack_sdk

    FakeWebClient.reset()
    monkeypatch.setattr(slack_sdk, "WebClient", FakeWebClient)
    return FakeWebClient


def _connector() -> SlackConnector:
    return SlackConnector(
        {
            "id": "inst1",
            "credentials_json": json.dumps(
                {"auth_mode": "manual", "fields": {"bot_token": "xoxb-test"}}
            ),
            "config_json": "{}",
        }
    )


def _write(resource: ResourceUri, text: str = "hello") -> Any:
    conn = sqlite3.connect(":memory:")
    return _connector().write(
        conn, resource, WritePayload(text=text), principal=PRINCIPAL, mode="execute"
    )


def test_write_channel_by_id() -> None:
    _write(ResourceUri(prefix="slack", kind="channel", resource_id="C0123"))
    posts = FakeWebClient.calls_named("chat_postMessage")
    assert posts == [{"channel": "C0123", "text": "hello"}]


def test_write_channel_by_name() -> None:
    _write(ResourceUri(prefix="slack", kind="channel", resource_id="#general"))
    assert FakeWebClient.calls_named("conversations_list")
    posts = FakeWebClient.calls_named("chat_postMessage")
    assert posts == [{"channel": "CGEN", "text": "hello"}]


def test_write_thread() -> None:
    _write(ResourceUri(prefix="slack", kind="thread", resource_id="C0123:1718.0001"))
    posts = FakeWebClient.calls_named("chat_postMessage")
    assert posts == [{"channel": "C0123", "text": "hello", "thread_ts": "1718.0001"}]


def test_write_dm_by_user_id() -> None:
    _write(ResourceUri(prefix="slack", kind="user", resource_id="U777"))
    opens = FakeWebClient.calls_named("conversations_open")
    assert opens == [{"users": "U777"}]
    posts = FakeWebClient.calls_named("chat_postMessage")
    assert posts == [{"channel": "D-U777", "text": "hello"}]


def test_write_dm_by_email() -> None:
    _write(ResourceUri(prefix="slack", kind="user", resource_id="dana@example.com"))
    lookups = FakeWebClient.calls_named("users_lookupByEmail")
    assert lookups == [{"email": "dana@example.com"}]
    posts = FakeWebClient.calls_named("chat_postMessage")
    assert posts == [{"channel": "D-U777", "text": "hello"}]


def test_write_dm_unknown_email_raises() -> None:
    with pytest.raises(ValueError, match="No Slack user found"):
        _write(ResourceUri(prefix="slack", kind="user", resource_id="ghost@example.com"))


def test_write_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="unsupported kind"):
        _write(ResourceUri(prefix="slack", kind="emoji", resource_id="x"))
