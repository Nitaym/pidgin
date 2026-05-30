from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from pidgin.db import apply_migrations, connect
from pidgin.services.workspace import WorkspaceSummary, get_singleton_workspace
from pidgin.workspace import WorkspaceError, resolve_workspace_paths

GOOGLE_USER_SESSION_KEY = "google_user"
OAUTH_STATE_SESSION_KEY = "oauth_state"


@dataclass
class GoogleUser:
    sub: str
    email: str
    name: str
    picture: str

    @classmethod
    def from_session(cls, data: dict[str, Any]) -> GoogleUser:
        return cls(
            sub=str(data["sub"]),
            email=str(data.get("email", "")),
            name=str(data.get("name", "")),
            picture=str(data.get("picture", "")),
        )

    def to_session(self) -> dict[str, str]:
        return {
            "sub": self.sub,
            "email": self.email,
            "name": self.name,
            "picture": self.picture,
        }


@dataclass
class WorkspaceSession:
    workspace_id: str
    slug: str
    display_name: str
    paths_root: str
    conn: sqlite3.Connection


def get_pidgin_home(request: Request) -> Path | None:
    raw = request.app.state.pidgin_home
    return Path(raw) if raw else None


def get_google_user(request: Request) -> GoogleUser | None:
    raw = request.session.get(GOOGLE_USER_SESSION_KEY)
    if not raw:
        return None
    return GoogleUser.from_session(raw)


def require_google_user(request: Request) -> GoogleUser:
    user = get_google_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def set_google_user(request: Request, user: GoogleUser) -> None:
    request.session[GOOGLE_USER_SESSION_KEY] = user.to_session()


def clear_google_user(request: Request) -> None:
    request.session.pop(GOOGLE_USER_SESSION_KEY, None)


def open_workspace_session(
    request: Request,
    workspace: WorkspaceSummary,
) -> WorkspaceSession:
    try:
        paths = resolve_workspace_paths(workspace.id, home=get_pidgin_home(request))
    except WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    conn = connect(paths.db_sqlite)
    apply_migrations(conn)
    row = conn.execute("SELECT display_name FROM workspace LIMIT 1").fetchone()
    display_name = row["display_name"] if row else workspace.display_name
    return WorkspaceSession(
        workspace_id=workspace.id,
        slug=workspace.slug,
        display_name=display_name,
        paths_root=str(paths.root),
        conn=conn,
    )


def require_workspace_session(request: Request, workspace_slug: str) -> WorkspaceSession:
    require_google_user(request)
    workspace = get_singleton_workspace(home=get_pidgin_home(request))
    if workspace is None:
        raise HTTPException(status_code=404, detail="No workspace yet")
    if workspace.slug != workspace_slug:
        raise HTTPException(status_code=404, detail="Unknown workspace")
    return open_workspace_session(request, workspace)
