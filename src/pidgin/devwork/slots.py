"""Dev slots: reusable git worktrees outside Dropbox that devs work in.

Same slots, layout and lock as the repo's own ticket runner (ActualGameplay
docs/agents.md): `<slots_dir>/slot-N`, sparse checkout without raw art and
research, reused branch after branch so each game's node_modules stays put.
A slot is taken while `<slot>/.agent/lock.json` names a live process; Pidgin
writes that lock for a dev's Claude Code, so the runner never starts a ticket
in a slot a dev is using, and a dev never gets a slot the runner is using.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from pidgin.devwork import proc as procs
from pidgin.util.ids import utc_now_iso

DEFAULTS = {
    "work_in": "folder",  # "folder" (each dev's own folder) or "slots"
    "slots_dir": r"D:\Work\apps\actual_gameplay\build_slots",
    "slots_repo": "",  # main checkout the slots belong to; defaults to the repo path
    "max_slots": "8",
}
SPARSE = ["/*", "!/artifacts/", "!/research/", "!/games/*/research/", "!**/assets/raw/", "!*.blend", "!*.mp4"]
_SLOT_RE = re.compile(r"^slot-(\d+)$")


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    out = dict(DEFAULTS)
    for row in conn.execute("SELECT key, value FROM dev_terminal_settings").fetchall():
        out[row["key"]] = row["value"]
    return out


def set_settings(conn: sqlite3.Connection, updates: dict[str, Any]) -> dict[str, str]:
    for key, value in updates.items():
        if key in DEFAULTS and value is not None:
            conn.execute(
                "INSERT INTO dev_terminal_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
    conn.commit()
    return get_settings(conn)


def _git(cwd: str | Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(result.stderr or result.stdout).strip()[:400]}")
    return result.stdout


def read_lock(slot_dir: Path) -> dict[str, Any] | None:
    try:
        return json.loads((slot_dir / ".agent" / "lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def lock_alive(lock: dict[str, Any] | None) -> bool:
    if not lock or not lock.get("pid"):
        return False
    return procs.is_alive(int(lock["pid"]), None)


def write_lock(slot_dir: str, *, pid: int, dev_name: str, branch: str | None) -> None:
    agent = Path(slot_dir) / ".agent"
    agent.mkdir(parents=True, exist_ok=True)
    (agent / "lock.json").write_text(
        json.dumps(
            {
                "ticket": None,
                "game": None,
                "mode": "pidgin-dev",
                "dev": dev_name,
                "branch": branch,
                "pid": pid,
                "started": utc_now_iso(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def clear_lock(slot_dir: str, pid: int | None) -> None:
    """Remove the lock only if it is still ours."""
    lock_file = Path(slot_dir) / ".agent" / "lock.json"
    lock = read_lock(Path(slot_dir))
    if lock and lock.get("mode") == "pidgin-dev" and (pid is None or lock.get("pid") == pid):
        try:
            lock_file.unlink()
        except OSError:
            pass


def list_slots(settings: dict[str, str], devs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root = Path(settings["slots_dir"])
    if not root.is_dir():
        return []
    by_slot = {d["slot"]: d for d in devs if d.get("slot")}
    out: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: int(_SLOT_RE.match(p.name).group(1)) if _SLOT_RE.match(p.name) else 1_000_000):
        m = _SLOT_RE.match(child.name)
        if not m or not (child / ".git").exists():
            continue
        lock = read_lock(child)
        alive = lock_alive(lock)
        branch = _git(child, "branch", "--show-current", check=False).strip()
        dirty = len([ln for ln in _git(child, "status", "--porcelain", check=False).splitlines() if ln.strip()])
        dev = by_slot.get(child.name)
        if dev:
            state, who = "dev", dev["name"]
        elif alive and lock and lock.get("ticket"):
            state, who = "runner", str(lock["ticket"])
        elif alive:
            state, who = "busy", str((lock or {}).get("dev") or "another process")
        else:
            state, who = "free", None
        out.append(
            {
                "name": child.name,
                "dir": str(child),
                "branch": branch or "(detached)",
                "dirty": dirty,
                "state": state,
                "who": who,
            }
        )
    return out


def _base(repo: str | Path) -> str:
    """Newest of local main and origin/main: slots share the repo's branches, and
    local main may hold commits not pushed yet."""
    has_origin = bool(_git(repo, "rev-parse", "--verify", "--quiet", "origin/main", check=False).strip())
    if not has_origin:
        return "main"
    ahead = subprocess.run(
        ["git", "merge-base", "--is-ancestor", "origin/main", "main"], cwd=str(repo), capture_output=True, check=False
    )
    return "main" if ahead.returncode == 0 else "origin/main"


def _create_slot(settings: dict[str, str], repo: str, name: str) -> Path:
    root = Path(settings["slots_dir"])
    root.mkdir(parents=True, exist_ok=True)
    slot_dir = root / name
    _git(repo, "fetch", "-q", "origin", check=False)
    base = _base(repo)
    _git(repo, "worktree", "add", "--no-checkout", "--detach", str(slot_dir), base)
    _git(slot_dir, "sparse-checkout", "init", "--no-cone")
    sparse = _git(slot_dir, "rev-parse", "--git-path", "info/sparse-checkout").strip()
    sparse_path = Path(sparse) if os.path.isabs(sparse) else slot_dir / sparse
    sparse_path.write_text("\n".join(SPARSE) + "\n", encoding="utf-8")
    _git(slot_dir, "checkout", "--detach", base)
    return slot_dir


def take_slot(
    settings: dict[str, str], repo: str, devs: list[dict[str, Any]], wanted: str | None = None
) -> tuple[str, str]:
    """(slot name, dir) for a dev: the wanted slot, the first free one, or a new one.

    A newly taken clean slot is moved to the newest main (detached), so
    the dev starts from current code; the branch it was on is left as it was.
    """
    slots = list_slots(settings, devs)
    if wanted:
        slot = next((s for s in slots if s["name"] == wanted), None)
        if slot is None:
            raise ValueError(f"No slot named {wanted}")
        if slot["state"] != "free":
            raise ValueError(f"{wanted} is in use ({slot['state']}: {slot['who']})")
    else:
        slot = next((s for s in slots if s["state"] == "free"), None)
    if slot is None:
        if len(slots) >= int(settings.get("max_slots") or 8):
            raise ValueError(f"All {len(slots)} slots are in use (limit {settings.get('max_slots')})")
        used = {s["name"] for s in slots}
        n = 1
        while f"slot-{n}" in used:
            n += 1
        slot_dir = _create_slot(settings, repo, f"slot-{n}")
        return f"slot-{n}", str(slot_dir)
    if slot["dirty"] == 0:
        _git(slot["dir"], "fetch", "-q", "origin", check=False)
        _git(slot["dir"], "switch", "--detach", _base(slot["dir"]), check=False)
    return slot["name"], slot["dir"]
