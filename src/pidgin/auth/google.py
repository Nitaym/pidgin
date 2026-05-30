from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx


@dataclass(frozen=True)
class GoogleSettings:
    client_id: str
    client_secret: str
    redirect_uri: str
    frontend_url: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    @classmethod
    def from_env(cls) -> GoogleSettings:
        return cls(
            client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
            client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            redirect_uri=os.environ.get(
                "GOOGLE_REDIRECT_URI",
                "http://127.0.0.1:8765/api/auth/google/callback",
            ),
            frontend_url=os.environ.get("PIDGIN_FRONTEND_URL", "http://127.0.0.1:5173"),
        )


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def google_login_url(settings: GoogleSettings, *, state: str) -> str:
    params = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_user(settings: GoogleSettings, code: str) -> dict[str, str]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "redirect_uri": settings.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]

        user_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_response.raise_for_status()
        profile = user_response.json()

    return {
        "sub": profile["sub"],
        "email": profile.get("email", ""),
        "name": profile.get("name", profile.get("email", "User")),
        "picture": profile.get("picture", ""),
    }


def new_oauth_state() -> str:
    return secrets.token_urlsafe(24)
