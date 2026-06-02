from __future__ import annotations

from pidgin.connectors import catalog as _catalog
from pidgin.connectors import pidgin_chat, slack
from pidgin.connectors.registry import register_connector_factory

register_connector_factory("pidgin_chat", pidgin_chat.connector.factory)
register_connector_factory("slack", slack.connector.factory)

INTEGRATION_CATALOG = _catalog.INTEGRATION_CATALOG

__all__ = ["INTEGRATION_CATALOG"]
