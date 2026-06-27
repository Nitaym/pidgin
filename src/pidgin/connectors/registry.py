from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from pidgin.connectors.base import ConnectorProtocol
from pidgin.connectors.catalog import catalog_entry
from pidgin.connectors.resources import connector_type_for_prefix, parse_resource_uri
from pidgin.connectors.types import ResourceUri

ConnectorFactory = Callable[[dict[str, Any]], ConnectorProtocol]

_FACTORIES: dict[str, ConnectorFactory] = {}


def register_connector_factory(connector_type: str, factory: ConnectorFactory) -> None:
    _FACTORIES[connector_type] = factory


def _row_to_installation(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "connector_type": row["connector_type"],
        "display_name": row["display_name"],
        "credentials_json": row["credentials_json"],
        "config_json": row["config_json"],
        "status": row["status"],
    }


def load_connector(conn: sqlite3.Connection, installation_id: str) -> ConnectorProtocol:
    row = conn.execute(
        "SELECT * FROM connector_installations WHERE id = ?",
        (installation_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Unknown connector installation: {installation_id}")
    factory = _FACTORIES.get(row["connector_type"])
    if factory is None:
        raise KeyError(f"No connector factory for type: {row['connector_type']}")
    return factory(_row_to_installation(row))


def load_connector_by_type(
    conn: sqlite3.Connection,
    connector_type: str,
    *,
    active_only: bool = True,
) -> ConnectorProtocol | None:
    query = """
        SELECT * FROM connector_installations
        WHERE connector_type = ?
    """
    params: list[Any] = [connector_type]
    if active_only:
        query += " AND status = 'active'"
    query += " ORDER BY installed_at ASC LIMIT 1"
    row = conn.execute(query, params).fetchone()
    if row is None:
        return None
    return load_connector(conn, row["id"])


def resolve_resource(conn: sqlite3.Connection, uri: str | ResourceUri) -> ConnectorProtocol:
    resource = uri if isinstance(uri, ResourceUri) else parse_resource_uri(uri)
    if resource.prefix == "pidgin_chat":
        factory = _FACTORIES.get("pidgin_chat")
        if factory is None:
            raise KeyError("pidgin_chat connector not registered")
        return factory({"id": None, "connector_type": "pidgin_chat"})

    installation_id = resource.query.get("installation_id")
    if installation_id:
        return load_connector(conn, installation_id)

    connector_type = connector_type_for_prefix(resource.prefix)
    loaded = load_connector_by_type(conn, connector_type, active_only=True)
    if loaded is None:
        raise KeyError(f"No active installation for connector type: {connector_type}")
    return loaded


def supported_connector_types() -> frozenset[str]:
    return frozenset(_FACTORIES.keys())


def ensure_connector_type(connector_type: str) -> None:
    if connector_type not in _FACTORIES:
        raise ValueError(f"Unsupported connector type: {connector_type}")
    if catalog_entry(connector_type) is None:
        raise ValueError(f"Unknown connector type in catalog: {connector_type}")
