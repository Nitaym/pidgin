from __future__ import annotations

import json
import secrets
import sqlite3
from typing import Any

from pidgin.connectors.catalog import INTEGRATION_CATALOG, catalog_entry
from pidgin.connectors.registry import ensure_connector_type, load_connector
from pidgin.connectors.slack.oauth import (
    build_slack_authorize_url,
    exchange_slack_code,
    slack_oauth_configured,
)
from pidgin.db.connectors import (
    create_installation,
    delete_installation,
    get_installation,
    list_installations,
    update_installation_status,
)


class IntegrationError(Exception):
    pass


def list_integrations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = list_installations(conn)
    catalog_by_type = {entry["connector_type"]: entry for entry in INTEGRATION_CATALOG}
    result: list[dict[str, Any]] = []
    for row in rows:
        entry = catalog_by_type.get(row["connector_type"], {})
        result.append(
            {
                **row,
                "config_json": json.loads(row["config_json"] or "{}"),
                "catalog_name": entry.get("name", row["connector_type"]),
            }
        )
    return result


def get_integration_catalog() -> list[dict[str, Any]]:
    return INTEGRATION_CATALOG


def connect_manual(
    conn: sqlite3.Connection,
    *,
    connector_type: str,
    display_name: str,
    fields: dict[str, str],
) -> dict[str, Any]:
    ensure_connector_type(connector_type)
    entry = catalog_entry(connector_type)
    if entry is None or "manual" not in entry.get("auth_modes", []):
        raise IntegrationError(f"Manual auth not supported for {connector_type}")

    required = [f["key"] for f in entry.get("manual_fields", []) if f.get("secret")]
    for key in required:
        if not fields.get(key):
            raise IntegrationError(f"Missing required field: {key}")

    credentials = {"auth_mode": "manual", "fields": fields}
    installation_id = create_installation(
        conn,
        connector_type=connector_type,
        display_name=display_name,
        credentials_json=credentials,
    )
    if connector_type == "slack":
        _store_slack_team_id(conn, installation_id)
    health = run_health_check(conn, installation_id)
    detail = get_installation(conn, installation_id)
    if detail is None:
        raise IntegrationError("Installation not found after create")
    detail["health"] = health
    return detail


def start_oauth(
    *,
    connector_type: str,
    workspace_slug: str,
    redirect_base: str,
) -> tuple[str, str]:
    ensure_connector_type(connector_type)
    entry = catalog_entry(connector_type)
    if entry is None or "oauth2" not in entry.get("auth_modes", []):
        raise IntegrationError(f"OAuth not supported for {connector_type}")

    if connector_type == "slack":
        if not slack_oauth_configured():
            raise IntegrationError(
                "Slack OAuth is not configured (SLACK_CLIENT_ID / SLACK_CLIENT_SECRET)"
            )
        state = secrets.token_urlsafe(24)
        oauth_state = json.dumps(
            {
                "state": state,
                "workspace_slug": workspace_slug,
                "connector_type": connector_type,
            }
        )
        redirect_uri = f"{redirect_base.rstrip('/')}/api/oauth/callback/slack"
        scopes = list(entry.get("oauth_scopes") or [])
        url = build_slack_authorize_url(state=state, redirect_uri=redirect_uri, scopes=scopes)
        return url, oauth_state

    raise IntegrationError(f"OAuth not implemented yet for {connector_type}")


async def complete_oauth(
    conn: sqlite3.Connection,
    *,
    connector_type: str,
    code: str,
    redirect_base: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    ensure_connector_type(connector_type)
    if connector_type == "slack":
        redirect_uri = f"{redirect_base.rstrip('/')}/api/oauth/callback/slack"
        tokens = await exchange_slack_code(code=code, redirect_uri=redirect_uri)
        credentials = {
            "auth_mode": "oauth2",
            "access_token": tokens["access_token"],
            "team_id": tokens["team_id"],
            "bot_user_id": tokens["bot_user_id"],
        }
        config = {"team_id": tokens["team_id"]}
        installation_id = create_installation(
            conn,
            connector_type="slack",
            display_name=display_name or "Slack",
            credentials_json=credentials,
            config_json=config,
        )
        health = run_health_check(conn, installation_id)
        detail = get_installation(conn, installation_id)
        if detail is None:
            raise IntegrationError("Installation not found after OAuth")
        detail["health"] = health
        return detail

    raise IntegrationError(f"OAuth callback not implemented for {connector_type}")


def _store_slack_team_id(conn: sqlite3.Connection, installation_id: str) -> None:
    """Manual installs don't include a team_id; resolve it via auth_test so
    webhook routing (find_by_type_and_team) can match strictly."""
    from pidgin.db.connectors import update_installation_config

    try:
        connector = load_connector(conn, installation_id)
        team_id = connector.resolve_team_id()  # type: ignore[attr-defined]
        if team_id:
            update_installation_config(conn, installation_id, {"team_id": team_id})
    except Exception:  # noqa: BLE001 — bad token surfaces via health check instead
        pass


def run_health_check(conn: sqlite3.Connection, installation_id: str) -> dict[str, Any]:
    connector = load_connector(conn, installation_id)
    status = connector.health_check(conn)
    update_installation_status(
        conn,
        installation_id,
        status="active" if status.ok else "errored",
        health_message=status.message,
    )
    return {"ok": status.ok, "message": status.message}


def disconnect(conn: sqlite3.Connection, installation_id: str) -> None:
    if not delete_installation(conn, installation_id):
        raise IntegrationError(f"Unknown installation: {installation_id}")


# Non-secret, user-editable config keys. Everything else in config_json is
# system-managed (team_id, last_health_message, ...).
_EDITABLE_CONFIG_KEYS = {"default_agent_handle"}


def update_integration_config(
    conn: sqlite3.Connection,
    *,
    installation_id: str,
    updates: dict[str, str],
) -> dict[str, Any]:
    from pidgin.db.connectors import update_installation_config

    unknown = set(updates) - _EDITABLE_CONFIG_KEYS
    if unknown:
        raise IntegrationError(f"Config keys not editable: {', '.join(sorted(unknown))}")
    detail = get_installation(conn, installation_id)
    if detail is None:
        raise IntegrationError(f"Unknown installation: {installation_id}")
    update_installation_config(conn, installation_id, dict(updates))
    refreshed = get_installation(conn, installation_id)
    return refreshed if refreshed is not None else detail
