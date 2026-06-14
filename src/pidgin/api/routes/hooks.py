from __future__ import annotations

import json
import os

from fastapi import APIRouter, HTTPException, Request, Response

from pidgin.api.deps import (
    OAUTH_STATE_SESSION_KEY,
    get_pidgin_home,
    open_workspace_session,
    require_google_user,
)
from pidgin.connectors.slack.ingress import (
    get_signing_secret,
    handle_slack_event,
    verify_slack_signature,
)
from pidgin.db import apply_migrations, connect
from pidgin.db.connectors import find_by_type_and_team
from pidgin.services.integrations import IntegrationError, complete_oauth
from pidgin.services.workspace import get_singleton_workspace
from pidgin.workspace import resolve_workspace_paths

router = APIRouter(tags=["hooks"])


def _verify_or_401(request: Request, body: bytes, signing_secret: str | None) -> None:
    if not signing_secret:
        # Verification is mandatory — a missing secret is a config error, not
        # a reason to accept unsigned payloads.
        raise HTTPException(
            status_code=401,
            detail="Slack signing secret not configured (set SLACK_SIGNING_SECRET)",
        )
    if not verify_slack_signature(
        signing_secret=signing_secret,
        timestamp=request.headers.get("X-Slack-Request-Timestamp", ""),
        body=body,
        signature=request.headers.get("X-Slack-Signature", ""),
    ):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")


@router.post("/hooks/slack/events")
async def slack_events_hook(request: Request) -> Response:
    body = await request.body()
    payload = json.loads(body.decode("utf-8"))

    if payload.get("type") == "url_verification":
        # Fired by Slack during app setup, possibly before any installation
        # exists. Verify with the app-level secret when present; echoing the
        # challenge has no side effects, so don't require an installation.
        env_secret = os.getenv("SLACK_SIGNING_SECRET")
        if env_secret:
            _verify_or_401(request, body, env_secret)
        return Response(content=payload.get("challenge", ""), media_type="text/plain")

    team_id = str(payload.get("team_id") or payload.get("team") or "")
    if not team_id and payload.get("event"):
        team_id = str(payload["event"].get("team") or "")

    home = get_pidgin_home(request)
    workspace = get_singleton_workspace(home=home)
    if workspace is None:
        raise HTTPException(status_code=404, detail="No workspace")

    paths = resolve_workspace_paths(workspace.id, home=home)
    conn = connect(paths.db_sqlite)
    apply_migrations(conn)

    installation_row = find_by_type_and_team(conn, "slack", team_id)
    if installation_row is None:
        raise HTTPException(status_code=404, detail="Slack not connected")

    installation = dict(installation_row)
    _verify_or_401(request, body, get_signing_secret(installation))

    event = payload.get("event") or {}
    # Persist only — the background worker runs the turn so we ack inside
    # Slack's 3s window. The envelope event_id dedups Slack's retries.
    handle_slack_event(
        conn,
        installation,
        event,
        external_event_id=str(payload.get("event_id") or "") or None,
        run_turn=False,
    )
    return Response(status_code=200)


@router.get("/api/oauth/callback/{connector_type}")
async def oauth_callback(
    connector_type: str,
    request: Request,
    code: str = "",
    state: str = "",
) -> Response:
    require_google_user(request)
    stored = request.session.get(OAUTH_STATE_SESSION_KEY)
    if not stored:
        raise HTTPException(status_code=400, detail="Missing OAuth session")
    parsed = json.loads(stored)
    if parsed.get("state") != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    workspace_slug = parsed.get("workspace_slug")
    if not workspace_slug:
        raise HTTPException(status_code=400, detail="Missing workspace in OAuth state")

    home = get_pidgin_home(request)
    workspace = get_singleton_workspace(home=home)
    if workspace is None or workspace.slug != workspace_slug:
        raise HTTPException(status_code=404, detail="Workspace not found")

    session = open_workspace_session(request, workspace)
    redirect_base = str(request.base_url).rstrip("/")
    display_name = request.session.pop("oauth_display_name", None)

    try:
        await complete_oauth(
            session.conn,
            connector_type=connector_type,
            code=code,
            redirect_base=redirect_base,
            display_name=str(display_name) if display_name else None,
        )
    except IntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        request.session.pop(OAUTH_STATE_SESSION_KEY, None)

    location = f"/{workspace_slug}/integrations/{connector_type}"
    return Response(status_code=302, headers={"Location": location})
