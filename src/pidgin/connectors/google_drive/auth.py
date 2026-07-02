from __future__ import annotations

import time
from typing import Any

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
# Full read/write scope — required to create/update files and folders. Reads
# still mint a readonly-scoped token; only writes request this broader scope.
DRIVE_WRITE_SCOPE = "https://www.googleapis.com/auth/drive"


class ServiceAccountError(ValueError):
    pass


def _build_assertion(
    service_account: dict[str, Any],
    *,
    scope: str,
    delegated_user: str | None,
    now: int,
) -> str:
    import jwt

    client_email = service_account.get("client_email")
    private_key = service_account.get("private_key")
    if not client_email or not private_key:
        raise ServiceAccountError(
            "Service account JSON missing client_email or private_key"
        )

    claims: dict[str, Any] = {
        "iss": client_email,
        "scope": scope,
        "aud": GOOGLE_TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }
    # Domain-wide delegation: impersonate a real user so the agent sees the
    # files that user can access (a bare service account owns nothing useful).
    if delegated_user:
        claims["sub"] = delegated_user

    try:
        return jwt.encode(claims, private_key, algorithm="RS256")
    except Exception as exc:  # noqa: BLE001 — bad key surfaces as a clear config error
        raise ServiceAccountError(f"Could not sign service account JWT: {exc}") from exc


def fetch_access_token(
    service_account: dict[str, Any],
    *,
    delegated_user: str | None = None,
    scope: str = DRIVE_READONLY_SCOPE,
) -> str:
    """Mint a short-lived Google access token from service account credentials.

    Signs an RS256 JWT assertion and exchanges it at Google's token endpoint
    (the two-legged OAuth "jwt-bearer" grant). Synchronous so it can be called
    from the sync connector ``read``/``health_check`` methods.
    """
    import httpx

    now = int(time.time())
    assertion = _build_assertion(
        service_account, scope=scope, delegated_user=delegated_user, now=now
    )
    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            GOOGLE_TOKEN_URL,
            data={"grant_type": JWT_BEARER_GRANT, "assertion": assertion},
        )
    if response.status_code != 200:
        detail = _error_detail(response)
        raise ServiceAccountError(f"Google token exchange failed: {detail}")
    token = response.json().get("access_token")
    if not token:
        raise ServiceAccountError("Google token response missing access_token")
    return str(token)


def _error_detail(response: Any) -> str:
    try:
        body = response.json()
        return str(body.get("error_description") or body.get("error") or response.text)
    except Exception:  # noqa: BLE001
        return response.text
