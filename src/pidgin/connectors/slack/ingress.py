from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import time
from typing import Any

from pidgin.db import insert_inbound_event
from pidgin.db.connectors import link_dedup_inbound_event, try_record_connector_event
from pidgin.db.employees import get_agent_by_handle
from pidgin.db.principals import upsert_slack_principal
from pidgin.types import InboundEventCreate, TriggerType, TrustLabel

log = logging.getLogger(__name__)

_AGENT_PREFIX = re.compile(
    r"^(?:(?:<@[A-Z0-9]+>\s*)+)?(?:(?P<handle>[a-z0-9_-]+)\s*,\s*)?(?P<body>.*)$",
    re.IGNORECASE | re.DOTALL,
)


def verify_slack_signature(
    *,
    signing_secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
) -> bool:
    if not timestamp or not signature:
        return False
    try:
        request_time = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - request_time) > 60 * 5:
        return False
    base = f"v0:{timestamp}:{body.decode('utf-8')}"
    digest = hmac.new(signing_secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature)


def strip_slack_mentions(text: str) -> str:
    cleaned = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    return re.sub(r"^@?pidgin\s+", "", cleaned, flags=re.IGNORECASE).strip()


def parse_agent_directive(text: str) -> tuple[str | None, str]:
    cleaned = strip_slack_mentions(text)
    match = _AGENT_PREFIX.match(cleaned)
    if not match:
        return None, cleaned
    handle = match.group("handle")
    body = (match.group("body") or "").strip()
    return (handle.lower() if handle else None), body


def default_agent_handle(installation: dict[str, Any]) -> str | None:
    config = json.loads(installation.get("config_json") or "{}")
    handle = config.get("default_agent_handle")
    return str(handle).lower() if handle else None


def _reply_unknown_handle(
    conn: sqlite3.Connection,
    installation: dict[str, Any],
    event: dict[str, Any],
    handle: str | None,
) -> None:
    """Post a short pointer back into the channel instead of dropping silently."""
    from pidgin.db.employees import list_agents

    try:
        handles = [a["handle"] for a in list_agents(conn) if a.get("handle")]
        hint = (
            f"I couldn't find an agent named `{handle}`." if handle
            else "I couldn't tell which agent you meant."
        )
        if handles:
            hint += " Available: " + ", ".join(f"`{h}`" for h in sorted(handles))
        hint += "\nAddress one with `@Pidgin <agent>, <message>`."

        from pidgin.connectors.slack.connector import SlackConnector

        channel = str(event.get("channel") or "")
        thread_ts = str(event.get("thread_ts") or event.get("ts") or "")
        if not channel:
            return
        client = SlackConnector(installation)._client()
        kwargs: dict[str, Any] = {"channel": channel, "text": hint}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        client.chat_postMessage(**kwargs)
    except Exception:  # noqa: BLE001 — a failed hint must not fail the webhook
        log.warning("[slack] failed to post unknown-handle hint", exc_info=True)


def handle_slack_event(
    conn: sqlite3.Connection,
    installation: dict[str, Any],
    event: dict[str, Any],
    *,
    external_event_id: str | None = None,
    run_turn: bool = False,
) -> str | None:
    if event.get("type") != "app_mention" and not (
        event.get("type") == "message" and event.get("channel_type") == "im"
    ):
        return None
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return None

    # Idempotency: Slack retries the same envelope event_id when an ack is
    # slow or errors. First delivery wins; everything else is a no-op.
    if external_event_id and not try_record_connector_event(
        conn, connector_type="slack", external_event_id=external_event_id
    ):
        log.info("[slack] duplicate event skipped — event_id=%s", external_event_id)
        return None

    text = str(event.get("text") or "")
    handle, body = parse_agent_directive(text)
    explicit_handle = handle is not None and get_agent_by_handle(conn, handle) is not None
    if not explicit_handle:
        # An unmatched leading token may just be the start of the message
        # (e.g. "@Pidgin hello, how are you") — fall back to the installation's
        # default agent with the full message intact.
        handle = default_agent_handle(installation)
        body = strip_slack_mentions(text)
    if not body:
        body = strip_slack_mentions(text) or text

    agent = get_agent_by_handle(conn, handle) if handle else None
    if agent is None:
        _reply_unknown_handle(conn, installation, event, handle)
        return None

    slack_user = str(event.get("user") or "unknown")
    principal_id = upsert_slack_principal(
        conn,
        slack_user_id=slack_user,
        display_name=slack_user,
    )

    payload = {
        "connector_type": "slack",
        "connector_installation_id": installation["id"],
        "external_channel_id": str(event.get("channel") or ""),
        "external_thread_id": str(event.get("thread_ts") or event.get("ts") or ""),
        "message_text": body,
        "raw_ref": {
            "team_id": event.get("team"),
            "ts": event.get("ts"),
            "event_id": event.get("client_msg_id"),
        },
        "mentioned_handles": [handle],
    }

    event_id = insert_inbound_event(
        conn,
        InboundEventCreate(
            trigger_type=TriggerType.DIRECT_ADDRESS,
            target_ai_employee_id=agent["id"],
            sender_principal_id=principal_id,
            trust_label=TrustLabel.INTERNAL_AUTHENTICATED,
            payload=payload,
        ),
    )
    if external_event_id:
        link_dedup_inbound_event(
            conn,
            connector_type="slack",
            external_event_id=external_event_id,
            inbound_event_id=event_id,
        )
    if run_turn:
        from pidgin.runtime.scheduler import run_once

        run_once(conn)
    return event_id


def get_signing_secret(installation: dict[str, Any]) -> str | None:
    """Resolve the signing secret for webhook verification.

    Manual installs carry it in credentials; OAuth installs don't (Slack's
    OAuth exchange never returns it), so fall back to SLACK_SIGNING_SECRET —
    the app-level secret from the same Slack app config as the client id.
    """
    creds = json.loads(installation.get("credentials_json") or "{}")
    if creds.get("auth_mode") == "manual":
        fields = creds.get("fields") or {}
        secret = fields.get("signing_secret")
        if secret:
            return str(secret)
    secret = creds.get("signing_secret")
    if secret:
        return str(secret)
    return os.getenv("SLACK_SIGNING_SECRET") or None
