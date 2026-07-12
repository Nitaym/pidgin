from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from typing import Any

import pytest

from pidgin.connectors.google_drive.connector import MAX_READ_BYTES, GoogleDriveConnector
from pidgin.connectors.types import PrincipalContext, ResourceUri
from pidgin.types import TrustLabel

PRINCIPAL = PrincipalContext(
    principal_id="p1",
    display_name="Agent",
    trust_label=TrustLabel.INTERNAL_AUTHENTICATED,
)

Handler = Callable[[str, dict[str, str]], "FakeResponse"]


class FakeResponse:
    def __init__(self, *, status_code: int = 200, payload: Any = None, content: bytes = b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.text = content.decode("utf-8", errors="replace") if content else ""

    def json(self) -> Any:
        return self._payload


class FakeClient:
    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, path: str, params: dict[str, str] | None = None) -> FakeResponse:
        params = params or {}
        self.requests.append((path, params))
        return self._handler(path, params)


def _connector(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> GoogleDriveConnector:
    connector = GoogleDriveConnector(
        {
            "id": "inst1",
            "credentials_json": json.dumps(
                {
                    "auth_mode": "manual",
                    "fields": {
                        "service_account_json": '{"client_email":"x","private_key":"k"}',
                        "delegated_user": "user@acme.com",
                    },
                }
            ),
            "config_json": "{}",
        }
    )
    monkeypatch.setattr(connector, "_access_token", lambda: "test-token")
    monkeypatch.setattr(connector, "_client", lambda token: FakeClient(handler))
    return connector


def _read(connector: GoogleDriveConnector, resource: ResourceUri) -> Any:
    conn = sqlite3.connect(":memory:")
    return connector.read(conn, resource, principal=PRINCIPAL)


def test_read_google_doc_exports_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(path: str, params: dict[str, str]) -> FakeResponse:
        if path == "/files/doc1" and "export" not in path:
            return FakeResponse(
                payload={
                    "id": "doc1",
                    "name": "Plan",
                    "mimeType": "application/vnd.google-apps.document",
                }
            )
        if path == "/files/doc1/export":
            assert params["mimeType"] == "text/plain"
            return FakeResponse(content=b"Quarterly plan body")
        raise AssertionError(f"unexpected request {path} {params}")

    connector = _connector(monkeypatch, handler)
    result = _read(connector, ResourceUri(prefix="gdrive", kind="file", resource_id="doc1"))
    assert result.text == "Quarterly plan body"
    assert result.metadata["name"] == "Plan"
    assert result.metadata["truncated"] is False


def test_read_binary_file_uses_alt_media(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(path: str, params: dict[str, str]) -> FakeResponse:
        if path == "/files/f2" and params.get("alt") != "media":
            return FakeResponse(
                payload={"id": "f2", "name": "notes.txt", "mimeType": "text/plain"}
            )
        if path == "/files/f2" and params.get("alt") == "media":
            return FakeResponse(content=b"raw text contents")
        raise AssertionError(f"unexpected request {path} {params}")

    connector = _connector(monkeypatch, handler)
    result = _read(connector, ResourceUri(prefix="gdrive", kind="file", resource_id="f2"))
    assert result.text == "raw text contents"
    assert result.metadata["mime_type"] == "text/plain"


def test_read_file_truncates_oversized(monkeypatch: pytest.MonkeyPatch) -> None:
    big = b"a" * (MAX_READ_BYTES + 500)

    def handler(path: str, params: dict[str, str]) -> FakeResponse:
        if path == "/files/big" and params.get("alt") != "media":
            return FakeResponse(
                payload={"id": "big", "name": "big.txt", "mimeType": "text/plain"}
            )
        return FakeResponse(content=big)

    connector = _connector(monkeypatch, handler)
    result = _read(connector, ResourceUri(prefix="gdrive", kind="file", resource_id="big"))
    assert result.metadata["truncated"] is True
    assert result.text.endswith("[... truncated ...]")
    assert len(result.text.encode("utf-8")) <= MAX_READ_BYTES + len("\n\n[... truncated ...]")


def test_read_folder_lists_children(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(path: str, params: dict[str, str]) -> FakeResponse:
        assert path == "/files"
        assert "'fold1' in parents" in params["q"]
        return FakeResponse(
            payload={
                "files": [
                    {"id": "c1", "name": "Doc A", "mimeType": "text/plain"},
                    {
                        "id": "c2",
                        "name": "Sub",
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                ]
            }
        )

    connector = _connector(monkeypatch, handler)
    result = _read(connector, ResourceUri(prefix="gdrive", kind="folder", resource_id="fold1"))
    assert "Doc A" in result.text
    assert "gdrive:file/c2" in result.text
    assert "folder" in result.text
    assert result.metadata["count"] == 2


def test_read_file_that_is_folder_lists_children(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(path: str, params: dict[str, str]) -> FakeResponse:
        if path == "/files/fold1" and "fields" in params:
            return FakeResponse(
                payload={
                    "id": "fold1",
                    "name": "Folder",
                    "mimeType": "application/vnd.google-apps.folder",
                }
            )
        assert path == "/files"
        return FakeResponse(payload={"files": []})

    connector = _connector(monkeypatch, handler)
    result = _read(connector, ResourceUri(prefix="gdrive", kind="file", resource_id="fold1"))
    assert result.text == "(empty folder)"


def test_read_unsupported_kind_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = _connector(monkeypatch, lambda p, q: FakeResponse())
    with pytest.raises(ValueError, match="unsupported kind"):
        _read(connector, ResourceUri(prefix="gdrive", kind="comment", resource_id="x"))


def test_read_api_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(path: str, params: dict[str, str]) -> FakeResponse:
        return FakeResponse(status_code=404, payload={"error": {"message": "Not found"}})

    connector = _connector(monkeypatch, handler)
    with pytest.raises(ValueError, match="Not found"):
        _read(connector, ResourceUri(prefix="gdrive", kind="file", resource_id="ghost"))


WriteHandler = Callable[[str, str, object], "FakeResponse"]


class WriteFakeClient:
    def __init__(self, handler: WriteHandler) -> None:
        self._handler = handler
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def __enter__(self) -> WriteFakeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def post(
        self,
        url: str,
        json: Any = None,
        params: dict[str, str] | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        self.calls.append(
            ("POST", url, {"json": json, "params": params, "content": content, "headers": headers})
        )
        return self._handler("POST", url, content if content is not None else json)

    def patch(
        self,
        url: str,
        params: dict[str, str] | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        self.calls.append(("PATCH", url, {"params": params, "content": content}))
        return self._handler("PATCH", url, content)

    def put(
        self,
        url: str,
        json: Any = None,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        self.calls.append(("PUT", url, {"json": json, "params": params}))
        return self._handler("PUT", url, json)


def _write_connector(
    monkeypatch: pytest.MonkeyPatch, handler: WriteHandler, scopes: list[str]
) -> tuple[GoogleDriveConnector, WriteFakeClient]:
    connector = GoogleDriveConnector(
        {
            "id": "inst1",
            "credentials_json": json.dumps(
                {
                    "auth_mode": "manual",
                    "fields": {"service_account_json": '{"client_email":"x","private_key":"k"}'},
                }
            ),
            "config_json": "{}",
        }
    )
    client = WriteFakeClient(handler)
    monkeypatch.setattr(connector, "_access_token", lambda scope=None: scopes.append(scope) or "t")
    monkeypatch.setattr(connector, "_client", lambda token: client)
    return connector, client


def _write(connector: GoogleDriveConnector, resource: ResourceUri, payload: Any) -> Any:
    return connector.write(
        sqlite3.connect(":memory:"), resource, payload, principal=PRINCIPAL, mode="execute"
    )


def test_write_creates_file_in_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    from pidgin.connectors.types import WritePayload

    def handler(method: str, url: str, body: object) -> FakeResponse:
        if method == "POST" and url.endswith("/drive/v3/files"):
            assert body == {"name": "Plan", "parents": ["FOLD"], "mimeType": "text/plain"}
            return FakeResponse(payload={"id": "new1", "name": "Plan"})
        if method == "PATCH" and "/upload/drive/v3/files/new1" in url:
            assert body == b"body text"
            return FakeResponse(payload={"id": "new1"})
        raise AssertionError(f"unexpected {method} {url}")

    scopes: list[str] = []
    connector, _ = _write_connector(monkeypatch, handler, scopes)
    result = _write(
        connector,
        ResourceUri(prefix="gdrive", kind="folder", resource_id="FOLD"),
        WritePayload(text="body text", subject="Plan"),
    )
    assert result.handle == "new1"
    assert result.external_ref["kind"] == "file"
    assert scopes == ["https://www.googleapis.com/auth/drive"]  # write uses full scope


def test_write_creates_native_google_doc(monkeypatch: pytest.MonkeyPatch) -> None:
    from pidgin.connectors.types import WritePayload

    def handler(method: str, url: str, body: object) -> FakeResponse:
        assert method == "POST"
        assert "/upload/drive/v3/files" in url  # multipart import, not a plain create
        text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
        # The target mimeType makes Drive convert the upload into a real Doc,
        # and the markdown body rides in the same multipart request.
        assert "application/vnd.google-apps.document" in text
        assert "# Onboarding" in text
        return FakeResponse(payload={"id": "doc9", "name": "Onboarding"})

    connector, _ = _write_connector(monkeypatch, handler, [])
    result = _write(
        connector,
        ResourceUri(prefix="gdrive", kind="folder", resource_id="FOLD"),
        WritePayload(text="# Onboarding\nWelcome", subject="Onboarding", extra={"kind": "doc"}),
    )
    assert result.external_ref["kind"] == "doc"
    assert result.handle == "doc9"


def test_write_creates_empty_google_doc_metadata_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from pidgin.connectors.types import WritePayload

    def handler(method: str, url: str, body: object) -> FakeResponse:
        # No content → metadata-only create against the Drive API (not upload).
        assert url.endswith("/drive/v3/files")
        assert isinstance(body, dict)
        assert body["mimeType"] == "application/vnd.google-apps.document"
        return FakeResponse(payload={"id": "doc0", "name": "Blank"})

    connector, client = _write_connector(monkeypatch, handler, [])
    result = _write(
        connector,
        ResourceUri(prefix="gdrive", kind="folder", resource_id="F"),
        WritePayload(subject="Blank", extra={"kind": "doc"}),
    )
    assert result.external_ref["kind"] == "doc"
    assert not any("/upload/" in c[1] for c in client.calls)  # no media upload for empty doc


def test_write_creates_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    from pidgin.connectors.types import WritePayload

    def handler(method: str, url: str, body: object) -> FakeResponse:
        assert method == "POST" and url.endswith("/drive/v3/files")
        assert body == {
            "name": "Reports",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["FOLD"],
        }
        return FakeResponse(payload={"id": "fold2", "name": "Reports"})

    connector, client = _write_connector(monkeypatch, handler, [])
    result = _write(
        connector,
        ResourceUri(prefix="gdrive", kind="folder", resource_id="FOLD"),
        WritePayload(subject="Reports", extra={"kind": "folder"}),
    )
    assert result.external_ref["kind"] == "folder"
    assert not any(c[0] == "PATCH" for c in client.calls)  # folders have no media upload


def test_write_editing_existing_file_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Editing an existing file is a gated mutation; the create-only connector
    # refuses it (no HTTP call is made).
    from pidgin.connectors.types import WritePayload

    connector, client = _write_connector(monkeypatch, lambda m, u, b: FakeResponse(), [])
    with pytest.raises(ValueError, match="requires owner approval"):
        _write(
            connector,
            ResourceUri(prefix="gdrive", kind="file", resource_id="f9"),
            WritePayload(text="new contents"),
        )
    assert client.calls == []


def test_write_draft_mode_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from pidgin.connectors.types import WritePayload

    connector, _ = _write_connector(monkeypatch, lambda m, u, b: FakeResponse(), [])
    with pytest.raises(ValueError, match="requires execute mode"):
        connector.write(
            sqlite3.connect(":memory:"),
            ResourceUri(prefix="gdrive", kind="folder", resource_id="F"),
            WritePayload(text="hi", subject="doc"),
            principal=PRINCIPAL,
            mode="draft",
        )


def test_write_unsupported_kind_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from pidgin.connectors.types import WritePayload

    connector, _ = _write_connector(monkeypatch, lambda m, u, b: FakeResponse(), [])
    with pytest.raises(ValueError, match="unsupported kind"):
        _write(
            connector,
            ResourceUri(prefix="gdrive", kind="comment", resource_id="x"),
            WritePayload(text="hi"),
        )


def test_read_spreadsheet_reads_all_tabs(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(path: str, params: dict[str, str]) -> FakeResponse:
        if path == "/files/sh1" and "fields" in params:
            return FakeResponse(
                payload={
                    "id": "sh1",
                    "name": "Plan",
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                }
            )
        if path == "https://sheets.googleapis.com/v4/spreadsheets/sh1":
            assert params["fields"] == "sheets.properties.title"
            return FakeResponse(
                payload={
                    "sheets": [
                        {"properties": {"title": "P&L"}},
                        {"properties": {"title": "Hiring"}},
                    ]
                }
            )
        if path == "https://sheets.googleapis.com/v4/spreadsheets/sh1/values:batchGet":
            assert params["ranges"] == ["P&L", "Hiring"]
            return FakeResponse(
                payload={
                    "valueRanges": [
                        {"values": [["Runway", "14"], ["Burn", "50"]]},
                        {"values": [["Role", "Eng"]]},
                    ]
                }
            )
        raise AssertionError(f"unexpected request {path} {params}")

    connector = _connector(monkeypatch, handler)
    result = _read(connector, ResourceUri(prefix="gdrive", kind="file", resource_id="sh1"))
    assert "## P&L" in result.text
    assert "Runway,14" in result.text
    assert "## Hiring" in result.text
    assert result.metadata["tabs"] == ["P&L", "Hiring"]


def test_write_update_sheet_cells(monkeypatch: pytest.MonkeyPatch) -> None:
    from pidgin.connectors.types import WritePayload

    def handler(method: str, url: str, body: object) -> FakeResponse:
        assert method == "PUT"
        assert url == "https://sheets.googleapis.com/v4/spreadsheets/sh1/values/P&L!B2"
        assert body == {"values": [["14"]]}
        return FakeResponse(payload={"updatedCells": 1})

    connector, client = _write_connector(monkeypatch, handler, [])
    result = _write(
        connector,
        ResourceUri(prefix="gdrive", kind="file", resource_id="sh1"),
        WritePayload(
            extra={
                "owner_approved": True,
                "op": "update_cells",
                "range": "P&L!B2",
                "values": [["14"]],
            }
        ),
    )
    assert result.external_ref["kind"] == "sheet"
    assert result.external_ref["op"] == "update"
    assert any(c[0] == "PUT" for c in client.calls)


def test_write_append_sheet_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    from pidgin.connectors.types import WritePayload

    def handler(method: str, url: str, body: object) -> FakeResponse:
        assert method == "POST"
        assert url.endswith("/spreadsheets/sh1/values/Blockers!A1:append")
        assert body == {"values": [["late vendor"]]}
        return FakeResponse(payload={"updates": {"updatedRows": 1}})

    connector, _ = _write_connector(monkeypatch, handler, [])
    result = _write(
        connector,
        ResourceUri(prefix="gdrive", kind="file", resource_id="sh1"),
        WritePayload(
            extra={
                "owner_approved": True,
                "op": "append_rows",
                "range": "Blockers!A1",
                "values": [["late vendor"]],
            }
        ),
    )
    assert result.external_ref["op"] == "append"


def test_write_file_approved_but_unknown_op_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # An approved file write still needs a supported op; no HTTP call otherwise.
    from pidgin.connectors.types import WritePayload

    connector, client = _write_connector(monkeypatch, lambda m, u, b: FakeResponse(), [])
    with pytest.raises(ValueError, match="op unsupported"):
        _write(
            connector,
            ResourceUri(prefix="gdrive", kind="file", resource_id="f9"),
            WritePayload(extra={"owner_approved": True}),
        )
    assert client.calls == []


def test_health_check_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(path: str, params: dict[str, str]) -> FakeResponse:
        assert path == "/about"
        return FakeResponse(payload={"user": {"emailAddress": "bot@acme.com"}})

    connector = _connector(monkeypatch, handler)
    status = connector.health_check(sqlite3.connect(":memory:"))
    assert status.ok is True
    assert "bot@acme.com" in status.message


def test_health_check_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = GoogleDriveConnector(
        {
            "id": "inst1",
            "credentials_json": json.dumps(
                {"auth_mode": "manual", "fields": {"service_account_json": "not-json"}}
            ),
            "config_json": "{}",
        }
    )
    status = connector.health_check(sqlite3.connect(":memory:"))
    assert status.ok is False
