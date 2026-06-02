from __future__ import annotations

import os
from urllib.parse import urlencode

SLACK_OAUTH_AUTHORIZE = "https://slack.com/oauth/v2/authorize"


def slack_oauth_configured() -> bool:
    return bool(os.getenv("SLACK_CLIENT_ID") and os.getenv("SLACK_CLIENT_SECRET"))


def build_slack_authorize_url(*, state: str, redirect_uri: str, scopes: list[str]) -> str:
    client_id = os.getenv("SLACK_CLIENT_ID")
    if not client_id:
        raise RuntimeError("SLACK_CLIENT_ID is not configured")
    params = {
        "client_id": client_id,
        "scope": ",".join(scopes),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{SLACK_OAUTH_AUTHORIZE}?{urlencode(params)}"


async def exchange_slack_code(*, code: str, redirect_uri: str) -> dict[str, str]:
    import httpx

    client_id = os.getenv("SLACK_CLIENT_ID")
    client_secret = os.getenv("SLACK_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Slack OAuth is not configured")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        response.raise_for_status()
        data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "Slack OAuth failed"))
    return {
        "access_token": str(data["access_token"]),
        "team_id": str((data.get("team") or {}).get("id", "")),
        "bot_user_id": str(data.get("bot_user_id") or ""),
    }
