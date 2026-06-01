from __future__ import annotations

import json
from pathlib import Path

from pidgin.util.ids import new_ulid, utc_now_iso


def append_template_version_audit(
    workspace_root: Path,
    *,
    slug: str,
    actor_principal_id: str,
    from_version: int | None,
    to_version: int,
    summary: str,
) -> None:
    audit_dir = workspace_root / "audit" / "template-versions"
    audit_dir.mkdir(parents=True, exist_ok=True)
    changes = {"from_version": from_version, "to_version": to_version}
    entry = {
        "id": new_ulid(),
        "occurred_at": utc_now_iso(),
        "actor_principal_id": actor_principal_id,
        "action": "template_version_create",
        "summary": summary,
        "changes_json": json.dumps(changes, separators=(",", ":")),
    }
    path = audit_dir / f"{slug}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, separators=(",", ":")) + "\n")
