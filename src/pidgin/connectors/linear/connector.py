"""Linear connector (connector_type ``linear``).

Auth: a personal API key of a dedicated Linear member (manual mode). The
developer worker acts as that member, so everything it writes in Linear shows
as that member, never as the owner. See specs/DEVELOPER_WORKER_SPEC.html §5.2.
"""

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
from pidgin.devwork.linear_api import LinearClient, LinearError


def api_key_from_installation(installation: dict[str, Any] | sqlite3.Row) -> str:
    raw = installation["credentials_json"] or "{}"
    creds = json.loads(raw)
    return str((creds.get("fields") or {}).get("api_key") or "")


def operator_emails(conn: sqlite3.Connection) -> set[str]:
    """Emails of human principals in this workspace (the owner and other people)."""
    try:
        rows = conn.execute(
            "SELECT email_address FROM principals "
            "WHERE type = 'workspace_member' AND email_address IS NOT NULL"
        ).fetchall()
    except sqlite3.Error:
        return set()
    return {str(row["email_address"]).lower() for row in rows}


class LinearConnector:
    connector_type = "linear"

    def __init__(self, installation: dict[str, Any]) -> None:
        self.installation_id = installation["id"]
        self._client = LinearClient(api_key_from_installation(installation))

    @property
    def client(self) -> LinearClient:
        return self._client

    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            connector_type=self.connector_type,
            display_name="Linear",
            capabilities=("read", "post", "execute", "poll"),
        )

    def read(
        self,
        conn: sqlite3.Connection,
        resource: ResourceUri,
        *,
        principal: PrincipalContext,
    ) -> ReadResult:
        _ = conn, principal
        if resource.kind == "issue":
            node = self._client.issue_full(resource.resource_id)
            lines = [
                f"{node['identifier']}: {node['title']}",
                f"Status: {(node.get('state') or {}).get('name')}",
                f"URL: {node.get('url')}",
                "",
                node.get("description") or "(no description)",
                "",
                "Comments:",
            ]
            for c in (node.get("comments") or {}).get("nodes", []):
                lines.append(
                    f"- {(c.get('user') or {}).get('name', '?')} ({c['createdAt']}): {c['body']}"
                )
            return ReadResult(text="\n".join(lines)[:32000], metadata={"id": node["id"]})
        raise LinearError(f"Unsupported Linear resource kind: {resource.kind}")

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
        if mode == "draft":
            raise LinearError("Linear has no drafts; stage the comment for approval instead")
        if resource.kind == "issue" and payload.text:
            issue = self._client.issue(resource.resource_id)
            comment_id = self._client.comment(issue.id, payload.text)
            return WriteResult(handle=comment_id, external_ref={"issue": issue.key})
        raise LinearError(f"Unsupported Linear write: {resource}")

    def health_check(self, conn: sqlite3.Connection) -> HealthStatus:
        try:
            info = self._client.viewer()
        except LinearError as exc:
            return HealthStatus(ok=False, message=str(exc))
        viewer = info["viewer"]
        org = info["organization"]
        email = str(viewer.get("email") or "")
        msg = (
            f"Connected as {viewer.get('name')} ({email}) in {org.get('urlKey') or org.get('name')}"
        )
        if email.lower() in operator_emails(conn):
            msg += (
                ". Warning: this key belongs to a person in this workspace; the developer "
                "would act as them. Use the developer's own Linear member."
            )
        teams = ", ".join(t["key"] for t in info["teams"])
        return HealthStatus(ok=True, message=f"{msg}. Teams: {teams}")


def factory(installation: dict[str, Any]) -> ConnectorProtocol:
    return LinearConnector(installation)
