from __future__ import annotations

import json
import sqlite3
from typing import Any

from pidgin.connectors.base import ConnectorProtocol, WriteMode
from pidgin.connectors.google_drive.auth import (
    DRIVE_READONLY_SCOPE,
    DRIVE_WRITE_SCOPE,
    fetch_access_token,
)
from pidgin.connectors.types import (
    ConnectorMetadata,
    HealthStatus,
    PrincipalContext,
    ReadResult,
    ResourceUri,
    WritePayload,
    WriteResult,
)

DRIVE_API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
TEXT_MIME = "text/plain; charset=utf-8"

# Cap text handed back to the LLM (AGENT_RUNTIME_SPEC §5.3 ~32 KB).
MAX_READ_BYTES = 32 * 1024

# Google-native types must be exported rather than downloaded; map each to the
# text-ish format we feed the model.
_EXPORT_MIME = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
_FOLDER_MIME = "application/vnd.google-apps.folder"


class GoogleDriveConnector:
    connector_type = "google_drive"

    def __init__(self, installation: dict[str, Any]) -> None:
        self.installation_id = installation["id"]
        self._credentials = json.loads(installation.get("credentials_json") or "{}")
        self._config = json.loads(installation.get("config_json") or "{}")

    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            connector_type=self.connector_type,
            display_name="Google Drive",
            capabilities=("read", "write"),
        )

    # -- auth -------------------------------------------------------------

    def _service_account(self) -> dict[str, Any]:
        auth_mode = self._credentials.get("auth_mode")
        if auth_mode != "manual":
            raise ValueError(
                "Google Drive currently supports service-account (manual) auth only"
            )
        fields = self._credentials.get("fields") or {}
        raw = fields.get("service_account_json")
        if not raw:
            raise ValueError("Google Drive service_account_json not configured")
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"service_account_json is not valid JSON: {exc}") from exc

    def _delegated_user(self) -> str | None:
        fields = self._credentials.get("fields") or {}
        user = fields.get("delegated_user")
        return str(user) if user else None

    def _access_token(self, scope: str = DRIVE_READONLY_SCOPE) -> str:
        return fetch_access_token(
            self._service_account(),
            delegated_user=self._delegated_user(),
            scope=scope,
        )

    def _client(self, token: str) -> Any:
        import httpx

        return httpx.Client(
            base_url=DRIVE_API,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

    # -- read -------------------------------------------------------------

    def read(
        self,
        conn: sqlite3.Connection,
        resource: ResourceUri,
        *,
        principal: PrincipalContext,
    ) -> ReadResult:
        _ = conn, principal
        token = self._access_token()
        with self._client(token) as client:
            if resource.kind == "file":
                return self._read_file(client, resource.resource_id)
            if resource.kind == "folder":
                return self._read_folder(client, resource.resource_id)
        raise ValueError(f"google_drive read unsupported kind: {resource.kind}")

    def _read_file(self, client: Any, file_id: str) -> ReadResult:
        meta = self._get_json(
            client, f"/files/{file_id}", params={"fields": "id,name,mimeType,size"}
        )
        name = meta.get("name", file_id)
        mime = meta.get("mimeType", "")

        if mime == _FOLDER_MIME:
            return self._read_folder(client, file_id)

        if mime in _EXPORT_MIME:
            export_mime = _EXPORT_MIME[mime]
            resp = client.get(
                f"/files/{file_id}/export", params={"mimeType": export_mime}
            )
        else:
            resp = client.get(f"/files/{file_id}", params={"alt": "media"})
        self._raise_for_status(resp, f"read file {file_id}")

        body = resp.content[:MAX_READ_BYTES]
        truncated = len(resp.content) > MAX_READ_BYTES
        text = body.decode("utf-8", errors="replace")
        if truncated:
            text += "\n\n[... truncated ...]"
        return ReadResult(
            text=text,
            metadata={
                "name": name,
                "mime_type": mime,
                "truncated": truncated,
                "file_id": file_id,
            },
        )

    def _read_folder(self, client: Any, folder_id: str) -> ReadResult:
        data = self._get_json(
            client,
            "/files",
            params={
                "q": f"'{folder_id}' in parents and trashed = false",
                "fields": "files(id,name,mimeType)",
                "pageSize": "100",
            },
        )
        files = data.get("files") or []
        lines = [
            f"- {f.get('name', '?')} "
            f"({'folder' if f.get('mimeType') == _FOLDER_MIME else f.get('mimeType', '?')}) "
            f"[gdrive:file/{f.get('id')}]"
            for f in files
        ]
        text = "\n".join(lines) if lines else "(empty folder)"
        return ReadResult(
            text=text[:MAX_READ_BYTES],
            metadata={"count": len(files), "folder_id": folder_id},
        )

    # -- write ------------------------------------------------------------

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
        # Creation is additive and ungated. Editing/deleting an existing file is
        # a mutation that must be owner-approved — that gate isn't wired yet, so
        # the connector only creates. A file-target write is therefore refused
        # (this also closes any ungated path, e.g. via `post`).
        if resource.kind == "file":
            raise ValueError(
                "Editing an existing Drive file requires owner approval, which is not "
                "available yet — this connector can only create new files and folders."
            )
        if mode != "execute":
            raise ValueError("Google Drive write requires execute mode")
        if resource.kind != "folder":
            raise ValueError(f"google_drive write unsupported kind: {resource.kind}")

        token = self._access_token(DRIVE_WRITE_SCOPE)
        with self._client(token) as client:
            kind = str((payload.extra or {}).get("kind") or "file")
            name = (payload.subject or "").strip() or "Untitled"
            if kind == "folder":
                return self._create_folder(client, parent_id=resource.resource_id, name=name)
            return self._create_file(
                client, parent_id=resource.resource_id, name=name, content=payload.text or ""
            )

    def _create_folder(self, client: Any, *, parent_id: str, name: str) -> WriteResult:
        body = {"name": name, "mimeType": _FOLDER_MIME, "parents": [parent_id]}
        resp = client.post(f"{DRIVE_API}/files", json=body, params={"fields": "id,name"})
        self._raise_for_status(resp, f"create folder in {parent_id}")
        data = resp.json()
        return WriteResult(
            handle=str(data.get("id") or ""),
            external_ref={"id": data.get("id"), "name": data.get("name"), "kind": "folder"},
        )

    def _create_file(self, client: Any, *, parent_id: str, name: str, content: str) -> WriteResult:
        # Two-step: create the metadata (with parent + name), then upload the
        # body. Simpler and more robust than hand-rolling a multipart/related.
        meta = {"name": name, "parents": [parent_id], "mimeType": "text/plain"}
        resp = client.post(f"{DRIVE_API}/files", json=meta, params={"fields": "id,name"})
        self._raise_for_status(resp, f"create file in {parent_id}")
        file_id = str(resp.json().get("id") or "")
        if content:
            up = client.patch(
                f"{UPLOAD_API}/files/{file_id}",
                params={"uploadType": "media"},
                content=content.encode("utf-8"),
                headers={"Content-Type": TEXT_MIME},
            )
            self._raise_for_status(up, f"upload content to {file_id}")
        return WriteResult(
            handle=file_id, external_ref={"id": file_id, "name": name, "kind": "file"}
        )

    # -- health -----------------------------------------------------------

    def health_check(self, conn: sqlite3.Connection) -> HealthStatus:
        _ = conn
        try:
            token = self._access_token()
            with self._client(token) as client:
                about = self._get_json(
                    client, "/about", params={"fields": "user(emailAddress)"}
                )
            email = (about.get("user") or {}).get("emailAddress", "unknown")
            return HealthStatus(ok=True, message=f"Connected to Google Drive as {email}")
        except Exception as exc:  # noqa: BLE001 — surfaced to operator via status row
            return HealthStatus(ok=False, message=str(exc))

    # -- helpers ----------------------------------------------------------

    def _get_json(self, client: Any, path: str, *, params: dict[str, str]) -> dict[str, Any]:
        resp = client.get(path, params=params)
        self._raise_for_status(resp, path)
        return resp.json()

    @staticmethod
    def _raise_for_status(resp: Any, what: str) -> None:
        if resp.status_code == 200:
            return
        try:
            err = resp.json().get("error", {})
            message = err.get("message") or resp.text
        except Exception:  # noqa: BLE001
            message = resp.text
        raise ValueError(f"Google Drive {what} failed ({resp.status_code}): {message}")


def factory(installation: dict[str, Any]) -> ConnectorProtocol:
    return GoogleDriveConnector(installation)
