from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from pidgin.db import apply_migrations, connect, init_workspace_db
from pidgin.db.employees import ensure_operator_principal
from pidgin.util.slug import normalize_slug, slugify
from pidgin.workspace.manager import (
    WorkspacePaths,
    create_workspace,
    ensure_home,
    registry_path,
)

log = logging.getLogger(__name__)


def _seed_platform_agents(conn: sqlite3.Connection, workspace_root: Path) -> None:
    """Pre-hire the agents listed in the workspace seed manifest.

    The starting team (e.g. the HR agent) is defined as data in
    ``recipes/workspace-seed.json``. Seeding must never block workspace creation
    — if it fails, the workspace is still usable and the agents can be hired
    later.
    """
    from pidgin.hire import seed_workspace_agents

    try:
        hired = seed_workspace_agents(conn, paths_root=workspace_root)
        if hired:
            log.info("[workspace] seeded agents: %s", ", ".join(hired))
    except Exception:  # noqa: BLE001 — seeding must not break workspace creation
        log.exception("[workspace] failed to seed workspace agents")


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
    _seed_platform_agents(conn, paths.root)
    return WorkspaceSummary(
        id=auth["workspace_id"],
        slug=normalized_slug,
        display_name=display_name,
        path=str(paths.root),
    )


def reconcile_workspace_agents(home: Path | None = None) -> dict[str, list[str]]:
    """Ensure every registered workspace has the seed-manifest agents hired.

    Reconciliation pass: the seed manifest (``recipes/workspace-seed.json``) is
    the desired state; the hired agents are the actual state. Seeding is
    idempotent — handles already taken and singleton roles already filled are
    skipped — so running this repeatedly converges each workspace onto the
    manifest without duplicating anything. That makes it safe to run at startup
    and lets a newly added seed agent (e.g. Enablement) backfill into workspaces
    created before it existed, with no hand-written migration.

    Returns ``{workspace_slug: [newly hired handles]}``. A failure on one
    workspace is logged and isolated — it never aborts the others.
    """
    from pidgin.hire import seed_workspace_agents

    results: dict[str, list[str]] = {}
    for workspace in list_registered_workspaces(home):
        paths = WorkspacePaths(root=Path(workspace.path))
        if not paths.db_sqlite.is_file():
            log.warning(
                "[reconcile] skipping %s: no db at %s",
                workspace.slug,
                paths.db_sqlite,
            )
            results[workspace.slug] = []
            continue
        try:
            conn = connect(paths.db_sqlite)
            apply_migrations(conn)
            hired = seed_workspace_agents(conn, paths_root=paths.root)
            if hired:
                log.info(
                    "[reconcile] %s: hired %s", workspace.slug, ", ".join(hired)
                )
            results[workspace.slug] = hired
        except Exception:  # noqa: BLE001 — one workspace must not abort the rest
            log.exception("[reconcile] failed for workspace %s", workspace.slug)
            results[workspace.slug] = []
    return results
