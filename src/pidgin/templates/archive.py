"""Per-workspace archive state for marketplace candidate profiles.

Bundled profiles ship read-only in the repo, so "archiving" one is a
per-workspace hide flag rather than a delete. Workspace profiles can be archived
too (a soft hide, distinct from delete). State lives as a small JSON file in the
workspace dir, consistent with the other workspace-local stores.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

ProfileSource = Literal["bundled", "workspace"]

_EMPTY: dict[str, list[str]] = {"bundled": [], "workspace": []}


def _archive_path(workspace_root: Path) -> Path:
    return workspace_root / "marketplace" / "archived.json"


def load_archived(workspace_root: Path) -> dict[str, list[str]]:
    path = _archive_path(workspace_root)
    if not path.is_file():
        return {"bundled": [], "workspace": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"bundled": [], "workspace": []}
    return {
        "bundled": list(data.get("bundled", [])),
        "workspace": list(data.get("workspace", [])),
    }


def is_archived(archived: dict[str, list[str]], source: str, identifier: str) -> bool:
    return identifier in archived.get(source, [])


def set_archived(
    workspace_root: Path,
    *,
    source: ProfileSource,
    identifier: str,
    archived: bool,
) -> dict[str, list[str]]:
    current = load_archived(workspace_root)
    items = set(current.get(source, []))
    if archived:
        items.add(identifier)
    else:
        items.discard(identifier)
    current[source] = sorted(items)
    path = _archive_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return current
