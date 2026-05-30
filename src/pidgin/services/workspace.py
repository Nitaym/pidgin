from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from pidgin.db.employees import ensure_operator_principal
from pidgin.db import apply_migrations, connect, init_workspace_db
from pidgin.util.slug import normalize_slug, slugify
from pidgin.workspace.manager import create_workspace, ensure_home, registry_path


@dataclass(frozen=True)
class WorkspaceSummary:
    id: str
    slug: str
    display_name: str
    path: str


def _entry_to_summary(entry: dict[str, str]) -> WorkspaceSummary:
    display_name = entry["display_name"]
    slug = entry.get("slug") or slugify(display_name)
    return WorkspaceSummary(
        id=entry["id"],
        slug=slug,
        display_name=display_name,
        path=entry["path"],
    )


def list_registered_workspaces(home: Path | None = None) -> list[WorkspaceSummary]:
    ensure_home(home)
    reg = json.loads(registry_path(home).read_text(encoding="utf-8"))
    return [_entry_to_summary(ws) for ws in reg.get("workspaces", [])]


def get_singleton_workspace(home: Path | None = None) -> WorkspaceSummary | None:
    workspaces = list_registered_workspaces(home)
    return workspaces[0] if workspaces else None


def get_workspace_by_slug(slug: str, home: Path | None = None) -> WorkspaceSummary | None:
    for workspace in list_registered_workspaces(home):
        if workspace.slug == slug:
            return workspace
    return None


def create_workspace_with_db(
    display_name: str,
    slug: str,
    home: Path | None = None,
) -> WorkspaceSummary:
    if get_singleton_workspace(home) is not None:
        raise HTTPException(status_code=409, detail="Workspace already exists")

    try:
        normalized_slug = normalize_slug(slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if get_workspace_by_slug(normalized_slug, home=home) is not None:
        raise HTTPException(status_code=409, detail="Slug is already taken")

    internal_secret = secrets.token_urlsafe(32)
    paths = create_workspace(display_name, internal_secret, normalized_slug, home=home)
    auth = json.loads(paths.auth_json.read_text(encoding="utf-8"))
    conn = connect(paths.db_sqlite)
    apply_migrations(conn)
    init_workspace_db(conn, auth["workspace_id"], display_name)
    ensure_operator_principal(conn)
    return WorkspaceSummary(
        id=auth["workspace_id"],
        slug=normalized_slug,
        display_name=display_name,
        path=str(paths.root),
    )
