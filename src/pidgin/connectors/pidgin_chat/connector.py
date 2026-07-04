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
from pidgin.db.chat import insert_message, list_messages


class PidginChatConnector:
    connector_type = "pidgin_chat"
    installation_id: str | None = None

    def __init__(self, installation: dict[str, Any] | None = None) -> None:
        _ = installation

    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            connector_type=self.connector_type,
            display_name="Pidgin chat",
            capabilities=("ingress", "read", "say"),
        )

    def read(
        self,
        conn: sqlite3.Connection,
        resource: ResourceUri,
        *,
        principal: PrincipalContext,
    ) -> ReadResult:
        _ = principal
        if resource.kind != "conversation":
            raise ValueError(f"pidgin_chat read unsupported kind: {resource.kind}")
        messages = list_messages(conn, resource.resource_id)
        lines = [
            f"[{m['created_at']}] {m['sender_display_name']}: {m['body_text']}"
            for m in messages
        ]
        return ReadResult(text="\n".join(lines), metadata={"message_count": len(messages)})

    def health_check(self, conn: sqlite3.Connection) -> HealthStatus:
        _ = conn
        return HealthStatus(ok=True, message="Pidgin chat is always available")

    def write(
        self,
        conn: sqlite3.Connection,
        resource: ResourceUri,
        payload: WritePayload,
        *,
        principal: PrincipalContext,
        mode: WriteMode,
    ) -> WriteResult:
        if mode != "execute":
            raise ValueError("pidgin_chat only supports execute (say) writes for MVP")
        if resource.kind != "conversation":
            raise ValueError(f"pidgin_chat write unsupported kind: {resource.kind}")
        if not payload.text:
            raise ValueError("say requires payload.text")

        extra = payload.extra
        attachments = {k: v for k, v in extra.items() if k != "originating_turn_id"}
        message_id = insert_message(
            conn,
            conversation_id=resource.resource_id,
            sender_principal_id=principal.principal_id,
            sender_display_name=principal.display_name,
            body_text=payload.text,
            originating_turn_id=extra.get("originating_turn_id"),
            attachments_json=json.dumps(attachments) if attachments else None,
        )
        return WriteResult(
            handle=message_id,
            external_ref={"conversation_id": resource.resource_id},
        )


def factory(installation: dict[str, Any]) -> ConnectorProtocol:
    return PidginChatConnector(installation)
