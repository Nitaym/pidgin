from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
import time
from typing import Any

from pidgin.db import insert_inbound_event
from pidgin.db.employees import get_agent_by_handle
from pidgin.db.principals import upsert_slack_principal
from pidgin.types import InboundEventCreate, TriggerType, TrustLabel

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
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return False
    base = f"v0:{timestamp}:{body.decode('utf-8')}"
    digest = hmac.new(signing_secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature)


def parse_agent_directive(text: str) -> tuple[str | None, str]:
    cleaned = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    cleaned = re.sub(r"^@?pidgin\s+", "", cleaned, flags=re.IGNORECASE).strip()
    match = _AGENT_PREFIX.match(cleaned)
    if not match:
        return None, cleaned
    handle = match.group("handle")
    body = (match.group("body") or "").strip()
    return (handle.lower() if handle else None), body


def handle_slack_event(
    conn: sqlite3.Connection,
    installation: dict[str, Any],
    event: dict[str, Any],
    *,
    run_turn: bool = True,
) -> str | None:
    if event.get("type") != "app_mention" and not (
        event.get("type") == "message" and event.get("channel_type") == "im"
    ):
        return None
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return None

    text = str(event.get("text") or "")
    handle, body = parse_agent_directive(text)
    if not handle:
        handle = "support"
    if not body:
        body = text

    agent = get_agent_by_handle(conn, handle)
    if agent is None:
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
    if run_turn:
        from pidgin.runtime.scheduler import run_once

        run_once(conn)
    return event_id


def get_signing_secret(installation: dict[str, Any]) -> str | None:
    creds = json.loads(installation.get("credentials_json") or "{}")
    if creds.get("auth_mode") == "manual":
        fields = creds.get("fields") or {}
        secret = fields.get("signing_secret")
        return str(secret) if secret else None
    return creds.get("signing_secret")
