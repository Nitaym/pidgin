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
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
TEXT_MIME = "text/plain; charset=utf-8"
GDOC_MIME = "application/vnd.google-apps.document"
MARKDOWN_MIME = "text/markdown; charset=utf-8"

# kinds that mean "a real Google Doc" (converted native doc), vs a plain-text file.
_DOC_KINDS = {"doc", "gdoc", "document", "google_doc", "googledoc"}

# Cap text handed back to the LLM (AGENT_RUNTIME_SPEC §5.3 ~32 KB).
MAX_READ_BYTES = 32 * 1024

# Google-native types must be exported rather than downloaded; map each to the
# text-ish format we feed the model. Spreadsheets are handled via the Sheets API
# (all tabs), not this first-tab-only CSV export.
_EXPORT_MIME = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.presentation": "text/plain",
}
_FOLDER_MIME = "application/vnd.google-apps.folder"
SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"


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

        if mime == SPREADSHEET_MIME:
            return self._read_spreadsheet(client, file_id, name)

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

    def _read_spreadsheet(self, client: Any, file_id: str, name: str) -> ReadResult:
        """Read every tab of a Google Sheet via the Sheets API.

        Drive's CSV export only yields the first tab; a plan workbook is
        multi-tab (P&L, objectives, hiring, …), so we list the tabs then
        ``values:batchGet`` them, rendering each as a titled CSV block. The
        Drive read scope already grants Sheets read — no new auth.
        """
        meta = client.get(
            f"{SHEETS_API}/{file_id}", params={"fields": "sheets.properties.title"}
        )
        self._raise_for_status(meta, f"read spreadsheet {file_id}")
        titles = [
            s.get("properties", {}).get("title", "")
            for s in (meta.json().get("sheets") or [])
        ]
        titles = [t for t in titles if t]
        if not titles:
            return ReadResult(
                text="(empty spreadsheet)",
                metadata={"name": name, "mime_type": SPREADSHEET_MIME, "file_id": file_id},
            )
        resp = client.get(
            f"{SHEETS_API}/{file_id}/values:batchGet",
            params={"ranges": titles, "majorDimension": "ROWS"},
        )
        self._raise_for_status(resp, f"read spreadsheet values {file_id}")
        ranges = resp.json().get("valueRanges") or []
        blocks: list[str] = []
        for title, value_range in zip(titles, ranges, strict=False):
            rows = value_range.get("values") or []
            body = "\n".join(",".join(str(cell) for cell in row) for row in rows)
            blocks.append(f"## {title}\n{body or '(empty)'}")
        text = "\n\n".join(blocks)
        truncated = len(text.encode("utf-8")) > MAX_READ_BYTES
        if truncated:
            text = text.encode("utf-8")[:MAX_READ_BYTES].decode("utf-8", errors="ignore")
            text += "\n\n[... truncated ...]"
        return ReadResult(
            text=text,
            metadata={
                "name": name,
                "mime_type": SPREADSHEET_MIME,
                "file_id": file_id,
                "tabs": titles,
                "truncated": truncated,
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
        extra = payload.extra or {}
        # Editing an existing file is a gated mutation. It lands here only as an
        # owner-approved execute: the execute action stamps ``owner_approved``
        # after the approval gate accepts it. Ungated post/say writes never set
        # that flag (and target channels, not Drive files), so this stays closed
        # to them.
        if resource.kind == "file":
            if not (mode == "execute" and extra.get("owner_approved")):
                raise ValueError(
                    "Editing an existing Drive file requires owner approval, which is "
                    "not available yet — this connector can only create new files and "
                    "folders."
                )
            op = str(extra.get("op") or "").lower()
            if op not in ("update_cells", "append_rows"):
                raise ValueError(
                    f"google_drive file update op unsupported: {op or '(none)'}"
                )
            token = self._access_token(DRIVE_WRITE_SCOPE)
            with self._client(token) as client:
                return self._write_sheet_values(
                    client, resource.resource_id, extra, append=(op == "append_rows")
                )
        if mode != "execute":
            raise ValueError("Google Drive write requires execute mode")
        if resource.kind != "folder":
            raise ValueError(f"google_drive write unsupported kind: {resource.kind}")

        token = self._access_token(DRIVE_WRITE_SCOPE)
        with self._client(token) as client:
            kind = str(extra.get("kind") or "file").lower()
            name = (payload.subject or "").strip() or "Untitled"
            if kind == "folder":
                return self._create_folder(client, parent_id=resource.resource_id, name=name)
            if kind in _DOC_KINDS:
                return self._create_gdoc(
                    client, parent_id=resource.resource_id, name=name, content=payload.text or ""
                )
            return self._create_file(
                client, parent_id=resource.resource_id, name=name, content=payload.text or ""
            )

    def _write_sheet_values(
        self, client: Any, file_id: str, extra: dict[str, Any], *, append: bool
    ) -> WriteResult:
        """Update or append cell values on a Google Sheet via the Sheets API.

        ``extra`` carries ``range`` (A1, e.g. ``"P&L!B2"``), ``values`` (a list of
        rows), and optional ``value_input`` (USER_ENTERED|RAW). The Drive write
        scope already grants Sheets write — no new auth.
        """
        a1 = str(extra.get("range") or "").strip()
        if not a1:
            raise ValueError('google_drive sheet write requires a "range" (e.g. "P&L!B2")')
        values = extra.get("values")
        if not isinstance(values, list) or not all(isinstance(row, list) for row in values):
            raise ValueError('google_drive sheet write requires "values" as a list of rows')
        value_input = str(extra.get("value_input") or "USER_ENTERED").upper()
        if value_input not in ("USER_ENTERED", "RAW"):
            value_input = "USER_ENTERED"
        if append:
            resp = client.post(
                f"{SHEETS_API}/{file_id}/values/{a1}:append",
                params={
                    "valueInputOption": value_input,
                    "insertDataOption": "INSERT_ROWS",
                },
                json={"values": values},
            )
        else:
            resp = client.put(
                f"{SHEETS_API}/{file_id}/values/{a1}",
                params={"valueInputOption": value_input},
                json={"values": values},
            )
        self._raise_for_status(resp, f"write sheet {file_id}")
        return WriteResult(
            handle=file_id,
            external_ref={
                "id": file_id,
                "kind": "sheet",
                "range": a1,
                "op": "append" if append else "update",
            },
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

    def _create_gdoc(self, client: Any, *, parent_id: str, name: str, content: str) -> WriteResult:
        """Create a *native* Google Doc, not a plain-text/markdown file.

        Setting the target mimeType to google-apps.document makes Drive convert
        the uploaded body into a real Doc. Markdown import is supported, so the
        agent's markdown becomes headings/lists in the Doc rather than a raw .md
        file (the 2026-07 "it made markdown, not Google Docs" report). An empty
        doc is a metadata-only create.
        """
        metadata = {"name": name, "parents": [parent_id], "mimeType": GDOC_MIME}
        if not content:
            resp = client.post(f"{DRIVE_API}/files", json=metadata, params={"fields": "id,name"})
            self._raise_for_status(resp, f"create doc in {parent_id}")
            data = resp.json()
            return WriteResult(
                handle=str(data.get("id") or ""),
                external_ref={"id": data.get("id"), "name": data.get("name"), "kind": "doc"},
            )

        boundary = "pidginGDocBoundary7b3f"
        body = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {MARKDOWN_MIME}\r\n\r\n"
            f"{content}\r\n"
            f"--{boundary}--"
        ).encode("utf-8")
        resp = client.post(
            f"{UPLOAD_API}/files",
            params={"uploadType": "multipart", "fields": "id,name"},
            content=body,
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        )
        self._raise_for_status(resp, f"create doc in {parent_id}")
        data = resp.json()
        return WriteResult(
            handle=str(data.get("id") or ""),
            external_ref={"id": data.get("id"), "name": data.get("name"), "kind": "doc"},
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
