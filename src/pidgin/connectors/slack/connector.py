from __future__ import annotations

import json
import sqlite3
from typing import Any

from pidgin.connectors.base import ConnectorProtocol, WriteMode
from pidgin.connectors.types import (
    ConnectorMetadata,
    HealthStatus,
    PrincipalContext,
    ReadResult,
    ResourceUri,
    WritePayload,
    WriteResult,
)


class SlackConnector:
    connector_type = "slack"

    def __init__(self, installation: dict[str, Any]) -> None:
        self.installation_id = installation["id"]
        self._credentials = json.loads(installation.get("credentials_json") or "{}")
        self._config = json.loads(installation.get("config_json") or "{}")

    def _bot_token(self) -> str:
        auth_mode = self._credentials.get("auth_mode")
        if auth_mode == "oauth2":
            token = self._credentials.get("access_token")
        else:
            fields = self._credentials.get("fields") or {}
            token = fields.get("bot_token")
        if not token:
            raise ValueError("Slack bot token not configured")
        return str(token)

    def _client(self) -> Any:
        from slack_sdk import WebClient

        return WebClient(token=self._bot_token())

    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            connector_type=self.connector_type,
            display_name="Slack",
            capabilities=("ingress", "read", "say", "post"),
        )

    def read(
        self,
        conn: sqlite3.Connection,
        resource: ResourceUri,
        *,
        principal: PrincipalContext,
    ) -> ReadResult:
        _ = conn, principal
        client = self._client()
        if resource.kind == "channel":
            result = client.conversations_history(channel=resource.resource_id, limit=20)
            messages = result.get("messages") or []
            lines = [f"[{m.get('ts')}] {m.get('user', '?')}: {m.get('text', '')}" for m in messages]
            return ReadResult(text="\n".join(reversed(lines)), metadata={"count": len(messages)})
        if resource.kind == "thread":
            channel, _, thread_ts = resource.resource_id.partition(":")
            result = client.conversations_replies(channel=channel, ts=thread_ts, limit=20)
            messages = result.get("messages") or []
            lines = [f"[{m.get('ts')}] {m.get('user', '?')}: {m.get('text', '')}" for m in messages]
            return ReadResult(text="\n".join(lines), metadata={"count": len(messages)})
        raise ValueError(f"slack read unsupported kind: {resource.kind}")

    def write(
        self,
        conn: sqlite3.Connection,
        resource: ResourceUri,
        payload: WritePayload,
        *,
        principal: PrincipalContext,
        mode: WriteMode,
    ) -> WriteResult:
        _ = conn, principal
        if mode != "execute":
            raise ValueError("Slack external send requires execute mode (approvals in Phase 3)")
        if not payload.text:
            raise ValueError("Slack message requires payload.text")

        client = self._client()
        channel = resource.resource_id if resource.kind == "channel" else resource.resource_id
        kwargs: dict[str, Any] = {"channel": channel, "text": payload.text}
        if resource.kind == "thread" and ":" in resource.resource_id:
            ch, _, thread_ts = resource.resource_id.partition(":")
            kwargs = {"channel": ch, "text": payload.text, "thread_ts": thread_ts}

        response = client.chat_postMessage(**kwargs)
        ts = response.get("ts", "")
        return WriteResult(handle=str(ts), external_ref={"channel": kwargs["channel"], "ts": ts})

    def health_check(self, conn: sqlite3.Connection) -> HealthStatus:
        _ = conn
        try:
            client = self._client()
            auth = client.auth_test()
            team = auth.get("team") or auth.get("team_id") or "unknown"
            return HealthStatus(ok=True, message=f"Connected to Slack team {team}")
        except Exception as exc:
            return HealthStatus(ok=False, message=str(exc))


def factory(installation: dict[str, Any]) -> ConnectorProtocol:
    return SlackConnector(installation)
