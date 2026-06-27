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


def test_write_not_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    from pidgin.connectors.types import WritePayload

    connector = _connector(monkeypatch, lambda p, q: FakeResponse())
    conn = sqlite3.connect(":memory:")
    with pytest.raises(ValueError, match="read-only MVP"):
        connector.write(
            conn,
            ResourceUri(prefix="gdrive", kind="file", resource_id="x"),
            WritePayload(text="hi"),
            principal=PRINCIPAL,
            mode="draft",
        )


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
