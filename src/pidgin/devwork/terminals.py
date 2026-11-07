"""Live Claude Code terminals: one interactive `claude` per dev, in a real PTY.

The owner types into these from Pidgin's Devs page (xterm.js over a
WebSocket). Each dev keeps one Claude Code session id, so after a server
restart or an exit its terminal comes back with `claude --resume`, with the
conversation intact. Runs on the machine's logged-in Claude subscription:
Pidgin's own API keys are removed from the environment.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from pidgin.devwork import slots as dev_slots
from pidgin.util.ids import new_ulid, utc_now_iso

log = logging.getLogger(__name__)

SCROLLBACK_BYTES = 400_000
DEFAULT_DEVS = 4
_STRIP_ENV = {
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_SSE_PORT",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
}


def _session_exists(session_id: str) -> bool:
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    projects = config / "projects"
    return projects.is_dir() and any(projects.glob(f"*/{session_id}.jsonl"))


# -- storage -------------------------------------------------------------------


def list_devs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM dev_terminals WHERE archived_at IS NULL ORDER BY position, created_at"
    ).fetchall()
    return [dict(r) for r in rows]


def get_dev(conn: sqlite3.Connection, dev_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM dev_terminals WHERE id = ? AND archived_at IS NULL", (dev_id,)
    ).fetchone()
    return dict(row) if row else None


def create_dev(
    conn: sqlite3.Connection, *, cwd: str, name: str | None = None, slot: str | None = None
) -> dict[str, Any]:
    used = {d["name"] for d in list_devs(conn)}
    if not name:
        n = 1
        while f"Dev {n}" in used:
            n += 1
        name = f"Dev {n}"
    pos = conn.execute(
        "SELECT COALESCE(MAX(position), 0) + 1 FROM dev_terminals WHERE archived_at IS NULL"
    ).fetchone()[0]
    dev_id = new_ulid()
    conn.execute(
        "INSERT INTO dev_terminals (id, name, cwd, session_id, position, created_at, slot) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (dev_id, name, cwd, str(uuid.uuid4()), pos, utc_now_iso(), slot),
    )
    conn.commit()
    dev = get_dev(conn, dev_id)
    assert dev is not None
    return dev


def ensure_default_devs(conn: sqlite3.Connection, cwd: str) -> list[dict[str, Any]]:
    """The page opens with devs ready; the first time, make four."""
    devs = list_devs(conn)
    if not devs and not conn.execute("SELECT 1 FROM dev_terminals LIMIT 1").fetchone():
        for _ in range(DEFAULT_DEVS):
            create_dev(conn, cwd=cwd)
        devs = list_devs(conn)
    return devs


def update_dev(conn: sqlite3.Connection, dev_id: str, **fields: Any) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("name", "cwd", "session_id", "position", "slot")}
    if not allowed:
        return
    conn.execute(
        f"UPDATE dev_terminals SET {', '.join(f'{k} = ?' for k in allowed)} WHERE id = ?",
        (*allowed.values(), dev_id),
    )
    conn.commit()


def archive_dev(conn: sqlite3.Connection, dev_id: str) -> None:
    conn.execute("UPDATE dev_terminals SET archived_at = ? WHERE id = ?", (utc_now_iso(), dev_id))
    conn.commit()


# -- live processes ------------------------------------------------------------


class DevTerminal:
    def __init__(self, dev: dict[str, Any]) -> None:
        self.id: str = dev["id"]
        self.cwd: str = dev["cwd"]
        self.session_id: str = dev["session_id"]
        self.name: str = dev["name"]
        self.slot: str | None = dev.get("slot")
        self.proc: Any = None
        self.buffer = bytearray()
        self.subs: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[str | None]]] = set()
        self.lock = threading.Lock()
        self.cols, self.rows = 120, 32
        self.exit_note: str | None = None
        self.preparing = False  # its slot is being made; Claude starts when it's ready

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.isalive()

    def start(self) -> None:
        if self.preparing:
            return
        from winpty import PtyProcess  # Windows ConPTY; only needed when a terminal opens

        exe = shutil.which("claude")
        if exe is None:
            self._emit("\r\n\x1b[31mClaude Code ('claude') isn't on PATH for the Pidgin server.\x1b[0m\r\n")
            return
        if not Path(self.cwd).is_dir():
            self._emit(f"\r\n\x1b[31mFolder not found: {self.cwd}\x1b[0m\r\n")
            return
        resume = _session_exists(self.session_id)
        argv = [exe, "--resume" if resume else "--session-id", self.session_id]
        env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
        env.setdefault("TERM", "xterm-256color")
        env["COLORTERM"] = "truecolor"
        self.exit_note = None
        self.proc = PtyProcess.spawn(argv, cwd=self.cwd, env=env, dimensions=(self.rows, self.cols))
        if self.slot:
            # Mark the slot taken, the same way the repo's ticket runner does.
            branch = None
            try:
                branch = dev_slots._git(self.cwd, "branch", "--show-current", check=False).strip() or None
            except Exception:  # noqa: BLE001
                pass
            # The lock names the Pidgin server, not this Claude process: the slot stays
            # the dev's while Pidgin runs, even between Claude Code restarts.
            dev_slots.write_lock(self.cwd, pid=os.getpid(), dev_name=self.name, branch=branch)
        threading.Thread(target=self._read_loop, name=f"devterm-{self.id[-6:]}", daemon=True).start()
        log.info("[devterm] started %s in %s (%s)", self.id, self.cwd, "resume" if resume else "new")

    def _read_loop(self) -> None:
        proc = self.proc
        while True:
            try:
                data = proc.read(8192)
            except EOFError:
                break
            except Exception as exc:  # noqa: BLE001 — a dead PTY ends the loop
                log.info("[devterm] read ended for %s: %r", self.id, exc)
                break
            if data:
                self._emit(data)
            elif not proc.isalive():
                break
        if proc is self.proc:
            code = proc.exitstatus if hasattr(proc, "exitstatus") else None
            self.exit_note = f"exited ({code})" if code is not None else "exited"
            self._emit(
                "\r\n\x1b[90m── Claude Code exited. Press Enter to start it again "
                "(the conversation is kept). ──\x1b[0m\r\n"
            )

    def _emit(self, text: str) -> None:
        with self.lock:
            self.buffer += text.encode("utf-8", errors="replace")
            if len(self.buffer) > SCROLLBACK_BYTES:
                del self.buffer[: len(self.buffer) - SCROLLBACK_BYTES]
            subs = list(self.subs)
        for loop, queue in subs:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, text)
            except RuntimeError:
                pass  # that browser tab's loop is gone

    def scrollback(self) -> str:
        with self.lock:
            return self.buffer.decode("utf-8", errors="replace")

    def write(self, data: str) -> None:
        if self.preparing:
            return
        if not self.alive:
            if "\r" in data or "\n" in data:
                self.start()
            return
        self.proc.write(data)

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = max(20, min(cols, 400)), max(5, min(rows, 200))
        if self.alive:
            try:
                self.proc.setwinsize(self.rows, self.cols)
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if self.slot:
            dev_slots.clear_lock(self.cwd, os.getpid())
        if proc is not None and proc.isalive():
            try:
                proc.terminate(force=True)
            except Exception:  # noqa: BLE001
                pass


class TerminalManager:
    def __init__(self) -> None:
        self._terms: dict[str, DevTerminal] = {}
        self._lock = threading.Lock()

    def get(self, dev: dict[str, Any], *, start: bool = True) -> DevTerminal:
        with self._lock:
            term = self._terms.get(dev["id"])
            if term is None:
                term = DevTerminal(dev)
                self._terms[dev["id"]] = term
        if start and term.proc is None and term.exit_note is None:
            term.start()
        return term

    def status(self, dev_id: str) -> str:
        term = self._terms.get(dev_id)
        if term is not None and term.preparing:
            return "preparing"
        if term is None or (term.proc is None and term.exit_note is None):
            return "idle"
        return "running" if term.alive else "exited"

    def stop(self, dev_id: str) -> None:
        with self._lock:
            term = self._terms.pop(dev_id, None)
        if term is not None:
            term.stop()

    def restart(self, dev: dict[str, Any]) -> None:
        """Same terminal object, so open browser tabs stay attached."""
        term = self.get(dev, start=False)
        term.stop()
        term.exit_note = None
        term._emit("\r\n\x1b[90m── Restarting Claude Code… ──\x1b[0m\r\n")
        term.start()

    def shutdown(self) -> None:
        with self._lock:
            terms, self._terms = list(self._terms.values()), {}
        for term in terms:
            term.stop()


_manager = TerminalManager()
_slot_lock = threading.Lock()  # one slot chosen at a time, so two devs never get the same one


def _db_path(conn: sqlite3.Connection) -> str:
    return str(conn.execute("PRAGMA database_list").fetchone()[2])


def prepare_slot(
    conn: sqlite3.Connection, dev: dict[str, Any], settings: dict[str, str], repo: str, wanted: str | None
) -> None:
    """Put a dev in a slot without making the caller wait.

    The terminal exists at once and says it is preparing; making or updating
    the slot (git worktree, checkout, fetch) runs on a thread, then Claude Code
    starts in the same terminal, so open browser tabs just see it come up.
    """
    from pidgin.db.connection import connect

    term = _manager.get(dev, start=False)
    term.preparing = True
    term.exit_note = None
    term._emit(f"\x1b[90m── Preparing {wanted or 'a dev slot'}… ──\x1b[0m\r\n")
    db_path = Path(_db_path(conn))

    def work() -> None:
        db = connect(db_path)
        try:
            with _slot_lock:
                others = [d for d in list_devs(db) if d["id"] != dev["id"]]
                name, path = dev_slots.take_slot(settings, repo, others, wanted)
                update_dev(db, dev["id"], slot=name, cwd=path, session_id=str(uuid.uuid4()))
                fresh = get_dev(db, dev["id"])
            if fresh is None:  # removed while its slot was being made
                term.preparing = False
                return
            term.cwd, term.slot, term.session_id = fresh["cwd"], fresh["slot"], fresh["session_id"]
            term.preparing = False
            term._emit(f"\x1b[90m── {name} ready: {path} ──\x1b[0m\r\n")
            term.start()
        except Exception as exc:  # noqa: BLE001 — shown in the terminal instead
            log.warning("[devterm] slot for %s failed: %r", dev["id"], exc)
            term.preparing = False
            term.exit_note = "slot failed"
            term.cwd = "(no slot)"
            term._emit(f"\r\n\x1b[31mCouldn't prepare a slot: {exc}\x1b[0m\r\n")
        finally:
            db.close()

    threading.Thread(target=work, name=f"devslot-{dev['id'][-6:]}", daemon=True).start()


def manager() -> TerminalManager:
    return _manager
