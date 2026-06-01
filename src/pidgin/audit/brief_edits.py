from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pidgin.util.ids import new_ulid, utc_now_iso


def append_brief_edit_audit(
    workspace_root: Path,
    *,
    employee_id: str,
    actor_principal_id: str,
    summary: str,
    changes: dict[str, Any],
) -> None:
    audit_dir = workspace_root / "audit" / "brief-edits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": new_ulid(),
        "occurred_at": utc_now_iso(),
        "actor_principal_id": actor_principal_id,
        "action": "brief_edit",
        "summary": summary,
        "changes_json": json.dumps(changes, separators=(",", ":")),
    }
    path = audit_dir / f"{employee_id}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, separators=(",", ":")) + "\n")
