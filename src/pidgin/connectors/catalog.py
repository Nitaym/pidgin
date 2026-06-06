from __future__ import annotations

from typing import Any

INTEGRATION_CATALOG: list[dict[str, Any]] = [
    {
        "connector_type": "pidgin_chat",
        "name": "Pidgin chat",
        "description": "Built-in workspace direct messages with agents.",
        "auth_modes": ["none"],
        "builtin": True,
        "capabilities": ["ingress", "read", "say"],
    },
    {
        "connector_type": "slack",
        "name": "Slack",
        "description": "Talk to agents via @Pidgin in your Slack workspace.",
        "auth_modes": ["oauth2", "manual"],
        "builtin": False,
        "capabilities": ["ingress", "read", "say", "post"],
        "oauth_scopes": ["app_mentions:read", "chat:write", "im:history", "im:read"],
        "manual_fields": [
            {"key": "bot_token", "label": "Bot token", "secret": True},
            {"key": "signing_secret", "label": "Signing secret", "secret": True},
        ],
    },
    {
        "connector_type": "gmail",
        "name": "Gmail",
        "description": "Route email to agents and draft replies.",
        "auth_modes": ["oauth2", "manual"],
        "builtin": False,
        "capabilities": ["ingress", "read", "draft", "execute"],
        "oauth_scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
        ],
        "manual_fields": [
            {"key": "email_address", "label": "Email address", "secret": False},
            {"key": "app_password", "label": "App password (dev only)", "secret": True},
        ],
    },
    {
        "connector_type": "google_drive",
        "name": "Google Drive",
        "description": "Let agents read files and folders you grant access to.",
        "auth_modes": ["oauth2", "manual"],
        "builtin": False,
        "capabilities": ["read", "draft"],
        "oauth_scopes": ["https://www.googleapis.com/auth/drive.readonly"],
        "manual_fields": [
            {"key": "service_account_json", "label": "Service account JSON", "secret": True},
            {"key": "delegated_user", "label": "Delegated user email", "secret": False},
        ],
    },
    {
        "connector_type": "google_meet",
        "name": "Google Meet",
        "description": "Read upcoming meetings and calendar holds.",
        "auth_modes": ["oauth2"],
        "builtin": False,
        "capabilities": ["read", "draft", "execute"],
        "oauth_scopes": [
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
        ],
    },
    {
        "connector_type": "zoom",
        "name": "Zoom",
        "description": "Read and schedule Zoom meetings.",
        "auth_modes": ["oauth2", "manual"],
        "builtin": False,
        "capabilities": ["read", "draft", "execute"],
        "manual_fields": [
            {"key": "account_id", "label": "Account ID", "secret": False},
            {"key": "client_id", "label": "Client ID", "secret": False},
            {"key": "client_secret", "label": "Client secret", "secret": True},
        ],
    },
]


def catalog_entry(connector_type: str) -> dict[str, Any] | None:
    for entry in INTEGRATION_CATALOG:
        if entry["connector_type"] == connector_type:
            return entry
    return None
