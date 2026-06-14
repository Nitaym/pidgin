from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pidgin.connectors.targets import resolve_post_target
from pidgin.db import apply_migrations, connect
from pidgin.db.principals import upsert_slack_principal


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db = connect(tmp_path / "db.sqlite")
    apply_migrations(db)
    return db


def test_resource_uri_passthrough(conn: sqlite3.Connection) -> None:
    resource = resolve_post_target(conn, "slack:channel/C0123")
    assert (resource.prefix, resource.kind, resource.resource_id) == ("slack", "channel", "C0123")


def test_thread_uri_passthrough(conn: sqlite3.Connection) -> None:
    resource = resolve_post_target(conn, "slack:thread/C0123:1718000000.000100")
    assert resource.kind == "thread"
    assert resource.resource_id == "C0123:1718000000.000100"


def test_channel_name_form(conn: sqlite3.Connection) -> None:
    resource = resolve_post_target(conn, "#general")
    assert (resource.prefix, resource.kind, resource.resource_id) == ("slack", "channel", "#general")


def test_email_resolves_known_principal(conn: sqlite3.Connection) -> None:
    principal_id = upsert_slack_principal(conn, slack_user_id="U555", display_name="Dana")
    conn.execute(
        "UPDATE principals SET email_address = ? WHERE id = ?",
        ("dana@example.com", principal_id),
    )
    conn.commit()
    resource = resolve_post_target(conn, "dana@example.com")
    assert (resource.prefix, resource.kind, resource.resource_id) == ("slack", "user", "U555")


def test_email_unknown_passes_through_for_connector_lookup(conn: sqlite3.Connection) -> None:
    resource = resolve_post_target(conn, "stranger@example.com")
    assert (resource.prefix, resource.kind, resource.resource_id) == (
        "slack",
        "user",
        "stranger@example.com",
    )


def test_garbage_target_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="Cannot resolve post target"):
        resolve_post_target(conn, "just some words")
    with pytest.raises(ValueError, match="Empty post target"):
        resolve_post_target(conn, "  ")
