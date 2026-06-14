"""Workspace seed manifest — agents pre-hired on workspace onboarding.

The set of pre-hired agents is **data**, not code: it lives in
``recipes/workspace-seed.json`` so the platform's starting team can change
without touching the hire logic. Seeding is idempotent, so the same runner is
safe at workspace creation and as a backfill on existing workspaces.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pidgin.hire.service import HireError, TemplateHireRequest, hire_with_template

log = logging.getLogger(__name__)

SEED_MANIFEST_PATH = (
    Path(__file__).resolve().parents[3] / "recipes" / "workspace-seed.json"
)


@dataclass(frozen=True)
class SeedAgent:
    recipe_id: str
    handle: str | None = None


def load_seed_manifest(path: Path | None = None) -> list[SeedAgent]:
    manifest_path = path or SEED_MANIFEST_PATH
    if not manifest_path.is_file():
        log.warning("[seed] manifest not found: %s", manifest_path)
        return []
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    agents: list[SeedAgent] = []
    for entry in data.get("agents", []):
        recipe_id = entry.get("recipe_id")
        if not recipe_id:
            continue
        agents.append(SeedAgent(recipe_id=recipe_id, handle=entry.get("handle")))
    return agents


def seed_workspace_agents(
    conn: sqlite3.Connection,
    *,
    paths_root: Path | str | None,
    manifest_path: Path | None = None,
) -> list[str]:
    """Pre-hire the agents listed in the seed manifest. Returns hired handles.

    Idempotent: an entry whose handle is already taken, or whose singleton role
    is already filled, is skipped rather than duplicated.
    """
    hired: list[str] = []
    for seed in load_seed_manifest(manifest_path):
        try:
            result = hire_with_template(
                conn,
                paths_root=paths_root,
                request=TemplateHireRequest(
                    template_source="bundled",
                    template_id=seed.recipe_id,
                    handle=seed.handle,
                ),
            )
            hired.append(result["handle"])
        except HireError as exc:
            log.info("[seed] skipping %s: %s", seed.recipe_id, exc)
    return hired
