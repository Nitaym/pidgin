from __future__ import annotations

import json
import sqlite3
from typing import Any

from pidgin.util.ids import new_ulid, utc_now_iso


def _parse_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    return json.loads(raw)


def mask_credentials(credentials_json: str | None) -> dict[str, Any] | None:
    if not credentials_json:
        return None
    data = json.loads(credentials_json)
    masked = dict(data)
    if "access_token" in masked:
        masked["access_token"] = "***"
    if "refresh_token" in masked:
        masked["refresh_token"] = "***"
    fields = masked.get("fields")
    visible_keys = {"email_address", "delegated_user", "account_id", "client_id"}
    if isinstance(fields, dict):
        masked["fields"] = {
            key: "***" if key not in visible_keys else value
            for key, value in fields.items()
        }
    return masked


def list_installations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, connector_type, display_name, config_json, status,
               installed_at, updated_at, last_health_check_at
        FROM connector_installations
        ORDER BY connector_type, display_name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_installation(conn: sqlite3.Connection, installation_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM connector_installations WHERE id = ?",
        (installation_id,),
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["credentials_masked"] = mask_credentials(row["credentials_json"])
    data.pop("credentials_json", None)
    return data


def get_installation_row(conn: sqlite3.Connection, installation_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM connector_installations WHERE id = ?",
        (installation_id,),
    ).fetchone()


def find_by_type_and_team(
    conn: sqlite3.Connection,
    connector_type: str,
    team_id: str,
) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT * FROM connector_installations
        WHERE connector_type = ? AND status = 'active'
        """,
        (connector_type,),
    ).fetchall()
    for row in rows:
        config = _parse_json(row["config_json"])
        creds = _parse_json(row["credentials_json"])
        if config.get("team_id") == team_id or creds.get("team_id") == team_id:
            return row
    # No fallback on a team_id mismatch — routing another workspace's events
    # into this installation would cross tenants. Only when the payload has
    # no team at all is a sole active installation an acceptable answer.
    if not team_id and len(rows) == 1:
        return rows[0]
    return None


def update_installation_config(
    conn: sqlite3.Connection,
    installation_id: str,
    updates: dict[str, Any],
) -> None:
    """Merge keys into an installation's config_json."""
    row = conn.execute(
        "SELECT config_json FROM connector_installations WHERE id = ?",
        (installation_id,),
    ).fetchone()
    if row is None:
        return
    config = _parse_json(row["config_json"])
    config.update(updates)
    conn.execute(
        "UPDATE connector_installations SET config_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(config), utc_now_iso(), installation_id),
    )
    conn.commit()


def create_installation(
    conn: sqlite3.Connection,
    *,
    connector_type: str,
    display_name: str,
    credentials_json: dict[str, Any],
    config_json: dict[str, Any] | None = None,
    status: str = "active",
) -> str:
    installation_id = new_ulid()
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO connector_installations (
          id, connector_type, display_name, credentials_json, config_json,
          status, installed_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            installation_id,
            connector_type,
            display_name,
            json.dumps(credentials_json),
            json.dumps(config_json or {}),
            status,
            now,
            now,
        ),
    )
    conn.commit()
    return installation_id


def update_installation_status(
    conn: sqlite3.Connection,
    installation_id: str,
    *,
    status: str,
    health_message: str | None = None,
) -> None:
    now = utc_now_iso()
    row = conn.execute(
        "SELECT config_json FROM connector_installations WHERE id = ?",
        (installation_id,),
    ).fetchone()
    config = _parse_json(row["config_json"] if row else None)
    if health_message is not None:
        config["last_health_message"] = health_message
    conn.execute(
        """
        UPDATE connector_installations
        SET status = ?, updated_at = ?, last_health_check_at = ?, config_json = ?
        WHERE id = ?
        """,
        (status, now, now, json.dumps(config), installation_id),
    )
    conn.commit()


def try_record_connector_event(
    conn: sqlite3.Connection,
    *,
    connector_type: str,
    external_event_id: str,
    inbound_event_id: str | None = None,
) -> bool:
    """Record an external event id for idempotency.

    Returns True when the id is new (caller should process the event) and
    False when it was already recorded (caller should skip — e.g. a Slack
    retry of an envelope we already ingested).
    """
    try:
        conn.execute(
            """
            INSERT INTO connector_event_dedup (
              connector_type, external_event_id, inbound_event_id, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (connector_type, external_event_id, inbound_event_id, utc_now_iso()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def link_dedup_inbound_event(
    conn: sqlite3.Connection,
    *,
    connector_type: str,
    external_event_id: str,
    inbound_event_id: str,
) -> None:
    conn.execute(
        """
        UPDATE connector_event_dedup SET inbound_event_id = ?
        WHERE connector_type = ? AND external_event_id = ?
        """,
        (inbound_event_id, connector_type, external_event_id),
    )
    conn.commit()


def delete_installation(conn: sqlite3.Connection, installation_id: str) -> bool:
    cursor = conn.execute(
        "DELETE FROM connector_installations WHERE id = ?",
        (installation_id,),
    )
    conn.commit()
    return cursor.rowcount > 0
