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


LOCK_MODES = ("pidgin-dev", "pidgin-run")


def write_lock(
    slot_dir: str,
    *,
    pid: int,
    dev_name: str,
    branch: str | None,
    ticket: str | None = None,
    mode: str = "pidgin-dev",
) -> None:
    agent = Path(slot_dir) / ".agent"
    agent.mkdir(parents=True, exist_ok=True)
    (agent / "lock.json").write_text(
        json.dumps(
            {
                "ticket": ticket,
                "game": None,
                "mode": mode,
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
    if lock and lock.get("mode") in LOCK_MODES and (pid is None or lock.get("pid") == pid):
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


# -- slots for the ticket runner (Pidgin's Developer Worker) --------------------


class NoFreeSlot(Exception):
    pass


def _common_dir(path: str | Path) -> str:
    out = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False).strip()
    return os.path.normcase(os.path.realpath(out)) if out else ""


def belongs_to(settings: dict[str, str], repo: str) -> bool:
    """True when the slots folder holds worktrees of this repo (so runs can use them)."""
    root = Path(settings["slots_dir"])
    if not repo:
        return False
    if root.is_dir():
        want = _common_dir(repo)
        for child in root.iterdir():
            if _SLOT_RE.match(child.name) and (child / ".git").exists():
                return bool(want) and _common_dir(child) == want
    configured = settings.get("slots_repo") or ""
    return bool(configured) and os.path.normcase(os.path.realpath(configured)) == os.path.normcase(
        os.path.realpath(repo)
    )


def free_run_slots(settings: dict[str, str], devs: list[dict[str, Any]]) -> int:
    """How many runs could start now: free clean slots plus slots still to be made."""
    slots = list_slots(settings, devs)
    free = len([s for s in slots if s["state"] == "free" and s["dirty"] == 0])
    return free + max(0, int(settings.get("max_slots") or 8) - len(slots))


def take_run_slot(
    settings: dict[str, str],
    repo: str,
    devs: list[dict[str, Any]],
    *,
    ticket: str,
    branch: str,
    prefer: str | None = None,
) -> tuple[str, str, bool]:
    """(slot name, dir, newly made) for a run, locked for it under this process.

    Only clean free slots: a slot with uncommitted work is left for whoever made
    it. ``prefer`` (the slot of the ticket's last run) wins when free, so a
    review round can resume its Claude session, which is stored per folder.
    The caller holds the slot lock shared with dev terminals and rewrites the
    lock with Claude's pid once it is running.
    """
    slots = list_slots(settings, devs)
    usable = [s for s in slots if s["state"] == "free" and s["dirty"] == 0]
    slot = next((s for s in usable if s["name"] == prefer), None) or (usable[0] if usable else None)
    created = False
    if slot is None:
        if len(slots) >= int(settings.get("max_slots") or 8):
            raise NoFreeSlot(f"All {len(slots)} dev slots are in use (limit {settings.get('max_slots')})")
        used = {s["name"] for s in slots}
        n = 1
        while f"slot-{n}" in used:
            n += 1
        name, path = f"slot-{n}", str(_create_slot(settings, repo, f"slot-{n}"))
        created = True
    else:
        name, path = slot["name"], slot["dir"]
    write_lock(path, pid=os.getpid(), dev_name=ticket, branch=branch, ticket=ticket, mode="pidgin-run")
    return name, path, created


def switch_to_branch(slot_dir: str, branch: str, base: str) -> None:
    """Put the slot on the ticket's branch: the only preparation a run needs.

    The branch is made from ``base`` (the newest of local and origin main when
    base is main) the first time, and checked out as it is after that.
    """
    if base == "main":
        base = _base(slot_dir)
    exists = _git(slot_dir, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).strip()
    if exists:
        _git(slot_dir, "switch", "--quiet", branch)
    else:
        _git(slot_dir, "switch", "--quiet", "-c", branch, base)
