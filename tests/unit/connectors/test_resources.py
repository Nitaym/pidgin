from __future__ import annotations

import pytest

from pidgin.connectors.resources import (
    ResourceUriError,
    connector_type_for_prefix,
    parse_resource_uri,
)
from pidgin.connectors.slack.ingress import parse_agent_directive


def test_parse_resource_uri_conversation() -> None:
    uri = parse_resource_uri("pidgin_chat:conversation/01JABC")
    assert uri.prefix == "pidgin_chat"
    assert uri.kind == "conversation"
    assert uri.resource_id == "01JABC"


def test_parse_resource_uri_with_query() -> None:
    uri = parse_resource_uri("slack:channel/C123?installation_id=01JXYZ")
    assert uri.prefix == "slack"
    assert uri.query["installation_id"] == "01JXYZ"


def test_parse_resource_uri_invalid() -> None:
    with pytest.raises(ResourceUriError):
        parse_resource_uri("not-a-uri")


def test_parse_gdrive_resource_uri() -> None:
    uri = parse_resource_uri("gdrive:file/1AbC")
    assert uri.prefix == "gdrive"
    assert uri.kind == "file"
    assert uri.resource_id == "1AbC"


def test_connector_type_for_prefix_maps_google() -> None:
    assert connector_type_for_prefix("gdrive") == "google_drive"
    assert connector_type_for_prefix("gmeet") == "google_meet"


def test_connector_type_for_prefix_passthrough() -> None:
    assert connector_type_for_prefix("slack") == "slack"


def test_parse_agent_directive_with_handle() -> None:
    handle, body = parse_agent_directive("@Pidgin jane, check this invoice")
    assert handle == "jane"
    assert body == "check this invoice"


def test_parse_agent_directive_slack_mention() -> None:
    handle, body = parse_agent_directive("<@U123> support, hello there")
    assert handle == "support"
    assert body == "hello there"
