"""The developer runner: Linear watcher + Claude Code executor (spec §5.3–5.5).

One background thread (``DevRunner``) inside the Pidgin server:
  * polls Linear for each enabled developer (outbound only, every 60–120 s),
  * applies the trigger rules and keeps the queue,
  * starts runs within the concurrency cap (claim, worktree, Claude Code),
  * monitors running runs (limits, stop requests, exit) and finalizes them,
  * on startup, reconciles runs left over from a previous process.

Each run's preparation (claim, worktree, setup command, spawn) happens on its
own short-lived thread so a slow ``npm ci`` never blocks monitoring.

v1 note: rules 1–2 and 5 are applied deterministically here; mentions and
comments (rules 3–4) are not wired yet. To continue a handed-off ticket, the
owner assigns it back to the developer in Todo; the comments go into the prompt.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pidgin.devwork import proc, store
from pidgin.devwork.linear_api import Issue, LinearClient, LinearError, LinearRateLimited
from pidgin.devwork.prompt import build_resume_prompt, build_rules, build_ticket_prompt
from pidgin.util.ids import utc_now_iso

log = logging.getLogger(__name__)

TICK_SECONDS = 3.0
META_TTL_SECONDS = 600


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _git(repo: Path, *args: str, check: bool = True, timeout: int = 120) -> str:
    result = subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


def linear_for_worker(conn: sqlite3.Connection, worker: dict[str, Any]) -> LinearClient:
    row = conn.execute(
        "SELECT credentials_json FROM connector_installations WHERE id = ?",
        (worker.get("linear_installation_id"),),
    ).fetchone()
    if row is None:
        raise LinearError("Linear is not connected for this developer")
    key = json.loads(row["credentials_json"] or "{}").get("fields", {}).get("api_key", "")
    return LinearClient(key)


def branch_for(worker: dict[str, Any], issue_key: str, linear_branch: str, title: str) -> str:
    key = issue_key.lower()
    tail = linear_branch.rsplit("/", 1)[-1] if linear_branch else ""
    slug = tail[len(key) + 1 :] if tail.startswith(key + "-") else ""
    if not slug:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:48].strip("-") or "work"
    pattern = worker.get("branch_pattern") or "claude/{key}-{slug}"
    return pattern.replace("{key}", key).replace("{slug}", slug)


def claude_session_exists(session_id: str) -> bool:
    """True when Claude Code still has this session's transcript on disk."""
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    projects = config / "projects"
    return projects.is_dir() and any(projects.glob(f"*/{session_id}.jsonl"))


def resumable_session(
    earlier_runs: list[dict[str, Any]], worktree: str
) -> tuple[dict[str, Any], str] | None:
    """The last earlier run's Claude session, if a new run can continue it.

    Only when that run worked in this same worktree (sessions are stored per
    working directory) and its transcript still exists. Otherwise the new run
    starts fresh from the full ticket.
    """
    if not earlier_runs:
        return None
    last = earlier_runs[-1]
    session = last.get("session_id")
    if not session or last.get("status") in ("queued", "claiming", "preparing", "running"):
        return None
    if os.path.normcase(str(last.get("worktree_path") or "")) != os.path.normcase(worktree):
        return None
    if not claude_session_exists(session):
        return None
    return last, session


def check_repo(path: str, base_branch: str = "main") -> dict[str, Any]:
    """Hire-time / settings-time repo checks shown in the UI (spec §4.2)."""
    checks: list[dict[str, str]] = []
    repo = Path(path) if path else None
    if repo is None or not repo.is_dir():
        return {"ok": False, "checks": [{"level": "error", "text": "Folder not found."}]}
    try:
        top = _git(repo, "rev-parse", "--show-toplevel")
    except (RuntimeError, OSError) as exc:
        return {"ok": False, "checks": [{"level": "error", "text": f"Not a git repo: {exc}"}]}
    ok = True
    try:
        sha = _git(repo, "rev-parse", "--short", base_branch)
        checks.append({"level": "ok", "text": f"Git repo · base branch {base_branch} @ {sha}"})
    except RuntimeError:
        ok = False
        checks.append({"level": "error", "text": f"No local branch '{base_branch}'."})
    top_path = Path(top)
    if (top_path / "CLAUDE.md").is_file():
        skills_dir = top_path / ".claude" / "skills"
        n = len([p for p in skills_dir.iterdir() if p.is_dir()]) if skills_dir.is_dir() else 0
        checks.append({"level": "ok", "text": f"CLAUDE.md found · {n} project skills"})
    else:
        checks.append({"level": "warn", "text": "No CLAUDE.md in the repo root."})
    try:
        dirty = _git(repo, "status", "--porcelain").splitlines()
    except RuntimeError:
        dirty = []
    if dirty:
        rules_dirty = [d for d in dirty if "CLAUDE.md" in d or ".claude/" in d]
        text = f"{len(dirty)} uncommitted changes in your checkout. Runs start from committed {base_branch}"
        if rules_dirty:
            text += (
                f"; {len(rules_dirty)} of them are CLAUDE.md / .claude files, which runs won't see"
            )
        checks.append({"level": "warn", "text": text + "."})
    lowered = str(top_path).lower()
    if "dropbox" in lowered or "onedrive" in lowered:
        checks.append(
            {
                "level": "warn",
                "text": "Repo is inside a synced folder. Keep the worktree folder outside it.",
            }
        )
    if shutil.which("claude") is None:
        ok = False
        checks.append({"level": "error", "text": "Claude Code CLI ('claude') not found on PATH."})
    return {"ok": ok, "checks": checks, "toplevel": top}


class DevRunner:
    def __init__(self, home: Path | None) -> None:
        self._home = home
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._db_path: Path | None = None
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._offsets: dict[str, int] = {}
        self._sizes: dict[str, int] = {}
        self._preparing: set[str] = set()
        self._meta: dict[str, tuple[float, dict[str, Any]]] = {}
        self._backoff_until: dict[str, float] = {}
        self._lock = threading.Lock()
        self._recovered = False

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="pidgin-devrunner", daemon=True)
        self._thread.start()
        log.info("[devrunner] started")

    def stop(self) -> None:
        # Runs are detached on purpose: they keep going and are re-attached on restart.
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None

    def _open(self) -> sqlite3.Connection | None:
        from pidgin.db import apply_migrations, connect
        from pidgin.services.workspace import get_singleton_workspace
        from pidgin.workspace import resolve_workspace_paths

        workspace = get_singleton_workspace(home=self._home)
        if workspace is None:
            return None
        paths = resolve_workspace_paths(workspace.id, home=self._home)
        self._db_path = Path(paths.db_sqlite)
        conn = connect(self._db_path)
        apply_migrations(conn)
        return conn

    def _run(self) -> None:
        conn: sqlite3.Connection | None = None
        while not self._stop.is_set():
            try:
                if conn is None:
                    conn = self._open()
                    if conn is None:
                        self._stop.wait(5)
                        continue
                if not self._recovered:
                    self._recover(conn)
                    self._recovered = True
                self.tick(conn)
            except Exception:  # noqa: BLE001 — the runner must never die on one bad tick
                log.exception("[devrunner] tick failed")
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                conn = None
            self._stop.wait(TICK_SECONDS)
        if conn is not None:
            conn.close()

    # -- one tick ----------------------------------------------------------------
    def tick(self, conn: sqlite3.Connection) -> None:
        for worker in store.list_enabled_workers(conn):
            if not (
                worker.get("linear_installation_id")
                and worker.get("team_id")
                and worker.get("repo_path")
            ):
                continue
            if self._poll_due(worker):
                self._poll(conn, worker)
                worker = store.get_worker(conn, worker["ai_employee_id"]) or worker
            self._admit(conn, worker)
        for run in store.active_runs(conn):
            if run["status"] == "running":
                self._monitor(conn, run)

    def _poll_due(self, worker: dict[str, Any]) -> bool:
        if time.monotonic() < self._backoff_until.get(worker["ai_employee_id"], 0):
            return False
        last = _parse(worker.get("last_poll_at"))
        interval = max(30, min(int(worker.get("poll_seconds") or 60), 600))
        return last is None or (_now() - last).total_seconds() >= interval

    def poll_now(self, conn: sqlite3.Connection, ai_employee_id: str) -> None:
        self._backoff_until.pop(ai_employee_id, None)
        store.update_worker(conn, ai_employee_id, {"last_poll_at": None})

    # -- watcher -------------------------------------------------------------------
    def _team_meta(self, client: LinearClient, worker: dict[str, Any]) -> dict[str, Any]:
        key = f"{worker['ai_employee_id']}:{worker['team_id']}"
        cached = self._meta.get(key)
        if cached and time.monotonic() - cached[0] < META_TTL_SECONDS:
            return cached[1]
        meta = client.team_meta(worker["team_id"])
        meta["state_ids"] = {str(s["name"]).lower(): s["id"] for s in meta["states"]}
        self._meta[key] = (time.monotonic(), meta)
        return meta

    def _state_id(self, meta: dict[str, Any], worker: dict[str, Any], role: str) -> str | None:
        return meta["state_ids"].get(str(worker["status_map"].get(role, "")).lower())

    def _poll(self, conn: sqlite3.Connection, worker: dict[str, Any]) -> None:
        wid = worker["ai_employee_id"]
        store.update_worker(conn, wid, {"last_poll_at": utc_now_iso()})
        try:
            client = linear_for_worker(conn, worker)
            if not worker.get("viewer_id"):
                info = client.viewer()
                store.update_worker(
                    conn,
                    wid,
                    {
                        "viewer_id": info["viewer"].get("id"),
                        "viewer_name": info["viewer"].get("name"),
                    },
                )
                worker = store.get_worker(conn, wid) or worker
            meta = self._team_meta(client, worker)
            todo_id = self._state_id(meta, worker, "todo")
            if not todo_id:
                raise LinearError(
                    f"No '{worker['status_map']['todo']}' status in team {worker.get('team_key')}"
                )
            issues = client.todo_issues(worker["team_id"], todo_id)
            queue = self._queue_from(conn, worker, issues)
            store.update_worker(
                conn,
                wid,
                {"queue": queue, "last_poll_ok_at": utc_now_iso(), "last_poll_error": None},
            )
            self._check_running_tickets(conn, client, worker, meta)
        except LinearRateLimited as exc:
            self._backoff_until[wid] = time.monotonic() + 600
            store.update_worker(conn, wid, {"last_poll_error": f"{exc} — backing off 10 min"})
        except Exception as exc:  # noqa: BLE001
            self._backoff_until[wid] = time.monotonic() + 120
            store.update_worker(conn, wid, {"last_poll_error": str(exc)[:500]})
            log.warning("[devrunner] poll failed for %s: %s", wid, exc)

    def _queue_from(
        self, conn: sqlite3.Connection, worker: dict[str, Any], issues: list[Issue]
    ) -> list[dict[str, Any]]:
        rules = worker["rules"]
        skip = {s.lower() for s in rules.get("skip_labels", [])}
        ready_label = str(rules.get("agent_ready_label") or "agent-ready").lower()
        viewer = worker.get("viewer_id")
        out: list[dict[str, Any]] = []
        for issue in issues:
            if issue.assignee_id == viewer and rules.get("assigned", True):
                klass = "assigned"
            elif (
                issue.assignee_id is None
                and rules.get("agent_ready", True)
                and issue.has_label(ready_label)
            ):
                klass = "agent_ready"
            else:
                continue  # Todo on its own is never a trigger.
            skipped = sorted(skip.intersection(issue.label_names))
            reason = ""
            if skipped:
                reason = f"Skipped: labelled {', '.join(skipped)}"
            elif issue.blocked:
                reason = "Skipped: blocked by another ticket"
            last = store.last_run_for_ticket(conn, issue.id)
            if last and last["status"] in store.ACTIVE_STATUSES:
                continue
            if (
                not reason
                and last
                and last["status"] == "cancelled"
                and last.get("ticket_updated_after_stop") == issue.updated_at
            ):
                reason = "Stopped; waiting for you to touch the ticket again"
            out.append(
                {
                    "id": issue.id,
                    "key": issue.key,
                    "title": issue.title,
                    "url": issue.url,
                    "class": klass,
                    "priority": issue.priority,
                    "created_at": issue.created_at,
                    "updated_at": issue.updated_at,
                    "follow_up": last is not None,
                    "last_status": last["status"] if last else None,
                    "reason": reason,
                }
            )

        def order(item: dict[str, Any]) -> tuple[int, int, str]:
            prio = item["priority"] if item["priority"] > 0 else 5
            return (0 if item["class"] == "assigned" else 1, prio, item["created_at"])

        out.sort(key=order)
        has_assigned = any(i["class"] == "assigned" and not i["reason"] for i in out)
        for item in out:
            if not item["reason"]:
                item["reason"] = (
                    "Waits until no assigned ticket is waiting"
                    if item["class"] == "agent_ready" and has_assigned
                    else "Waiting for a free slot"
                )
        return out

    def _check_running_tickets(
        self,
        conn: sqlite3.Connection,
        client: LinearClient,
        worker: dict[str, Any],
        meta: dict[str, Any],
    ) -> None:
        """Rule 5: the owner can stop a run from Linear (cancel / backlog / unassign)."""
        for run in store.active_runs(conn, worker["ai_employee_id"]):
            if run["status"] != "running":
                continue
            try:
                issue = client.issue(run["ticket_id"])
            except LinearError:
                continue
            if issue.assignee_id != worker.get("viewer_id") or issue.state_type in (
                "canceled",
                "backlog",
            ):
                if not run["stop_requested"]:
                    store.update_run(conn, run["id"], stop_requested=1, stopped_by="Linear")
                    store.add_event(
                        conn,
                        run["id"],
                        "stop",
                        f"Stopped from Linear (status {issue.state_name}, assignee {issue.assignee_name or 'none'})",
                    )

    # -- admission -------------------------------------------------------------------
    def _admit(self, conn: sqlite3.Connection, worker: dict[str, Any]) -> None:
        active = store.active_runs(conn, worker["ai_employee_id"])
        slots = int(worker.get("max_concurrent") or 1) - len(active)
        if slots <= 0:
            return
        queue = [
            q
            for q in worker["queue"]
            if q["reason"]
            in ("Waiting for a free slot", "Waits until no assigned ticket is waiting")
        ]
        assigned = [q for q in queue if q["class"] == "assigned"]
        picks = assigned[:slots]
        if not assigned:
            picks = [q for q in queue if q["class"] == "agent_ready"][:slots]
        if not picks:
            return
        remaining = [q for q in worker["queue"] if q["id"] not in {p["id"] for p in picks}]
        for item in picks:
            klass = item["class"]
            if item.get("follow_up"):
                klass = (
                    "retry" if item.get("last_status") in ("failed", "timed_out") else "follow_up"
                )
            run_id = store.create_run(
                conn,
                ai_employee_id=worker["ai_employee_id"],
                ticket_id=item["id"],
                ticket_key=item["key"],
                ticket_title=item["title"],
                ticket_url=item["url"],
                trigger_class=klass,
            )
            if run_id is None:
                continue
            store.add_event(
                conn, run_id, "queued", f"Queued ({item['class'].replace('_', '-')} ticket in Todo)"
            )
            self._start_prepare(run_id, recovering=False)
        store.update_worker(conn, worker["ai_employee_id"], {"queue": remaining})

    def _start_prepare(self, run_id: str, *, recovering: bool) -> None:
        with self._lock:
            if run_id in self._preparing:
                return
            self._preparing.add(run_id)
        threading.Thread(
            target=self._prepare_and_launch,
            args=(run_id, recovering),
            name=f"devrun-{run_id[-6:]}",
            daemon=True,
        ).start()

    # -- prepare + launch (own thread) ---------------------------------------------
    def _prepare_and_launch(self, run_id: str, recovering: bool) -> None:
        from pidgin.db import connect

        assert self._db_path is not None
        conn = connect(self._db_path)
        try:
            self._prepare(conn, run_id, recovering)
        except Exception as exc:  # noqa: BLE001
            log.exception("[devrunner] prepare failed for %s", run_id)
            run = store.get_run(conn, run_id)
            if run and run["status"] in ("claiming", "preparing", "queued"):
                claimed = run["status"] != "queued"
                self._fail(conn, run, f"Could not start: {exc}", claimed=claimed)
        finally:
            with self._lock:
                self._preparing.discard(run_id)
            conn.close()

    def _prepare(self, conn: sqlite3.Connection, run_id: str, recovering: bool) -> None:
        run = store.get_run(conn, run_id)
        assert run is not None
        worker = store.get_worker(conn, run["ai_employee_id"])
        assert worker is not None
        client = linear_for_worker(conn, worker)
        meta = self._team_meta(client, worker)
        viewer = worker["viewer_id"]
        in_progress = self._state_id(meta, worker, "in_progress")

        # 1. Claim, with a live re-check (never start a ticket someone else took).
        store.update_run(conn, run_id, status="claiming")
        issue = client.issue(run["ticket_id"])
        already_ours = issue.state_id == in_progress and issue.assignee_id == viewer
        eligible = issue.state_id == self._state_id(meta, worker, "todo") and (
            issue.assignee_id == viewer
            or (issue.assignee_id is None and run["trigger_class"] == "agent_ready")
        )
        if not (eligible or (recovering and already_ours)):
            store.update_run(
                conn,
                run_id,
                status="dropped",
                ended_at=utc_now_iso(),
                failure_reason=f"No longer eligible (status {issue.state_name}, assignee {issue.assignee_name or 'none'})",
            )
            store.add_event(
                conn, run_id, "dropped", "Dropped: the ticket changed before it started"
            )
            return
        if not already_ours:
            client.update_issue(issue.id, state_id=in_progress, assignee_id=viewer)
            client.comment(
                issue.id,
                f"**Started:** picking this up (attempt {run['attempt']}). "
                "I'll comment as I go and finish with a hand-off or Done.",
            )
            store.add_event(
                conn,
                run_id,
                "claimed",
                f"Claimed: {worker['status_map']['in_progress']}, assigned to {worker.get('viewer_name') or 'the developer'}",
            )

        # 2. Worktree on a branch per ticket.
        store.update_run(conn, run_id, status="preparing")
        repo = Path(worker["repo_path"])
        base = worker.get("base_branch") or "main"
        branch = branch_for(worker, issue.key, issue.branch_name, issue.title)
        root = Path(worker.get("worktree_root") or store.default_worktree_root("developer"))
        root.mkdir(parents=True, exist_ok=True)
        path = root / issue.key
        created = False
        existing = self._worktree_for_branch(repo, branch)
        if existing:
            path = existing
        elif not (path / ".git").exists():
            if _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False):
                _git(repo, "worktree", "add", str(path), branch)
            else:
                _git(repo, "worktree", "add", "-b", branch, str(path), base)
            created = True
        base_sha = _git(repo, "rev-parse", base)
        log_dir = self._db_path.parent / "runs" / run_id if self._db_path else path / ".pidgin-run"
        log_dir.mkdir(parents=True, exist_ok=True)
        store.update_run(
            conn,
            run_id,
            branch=branch,
            worktree_path=str(path),
            base_sha=base_sha,
            log_dir=str(log_dir),
        )
        store.add_event(
            conn,
            run_id,
            "worktree",
            f"Worktree {'created' if created else 'reused'}: {path} on {branch}",
        )

        setup = (worker.get("setup_command") or "").strip()
        if created and setup:
            t0 = time.monotonic()
            with open(log_dir / "setup.log", "ab") as out:
                result = subprocess.run(  # noqa: S602 — the owner's own setup command
                    setup,
                    shell=True,
                    cwd=str(path),
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    timeout=1800,
                    check=False,
                )
            if result.returncode != 0:
                raise RuntimeError(
                    f"setup command '{setup}' failed with exit code {result.returncode} (see setup.log)"
                )
            store.add_event(
                conn, run_id, "setup", f"Setup '{setup}' done in {int(time.monotonic() - t0)} s"
            )

        # 3. Prompt, rules, ticket tools, then Claude Code.
        full = client.issue_full(issue.id)
        earlier = [r for r in store.runs_for_ticket(conn, issue.id) if r["id"] != run_id]
        resume_from = resumable_session(earlier, str(path))
        if resume_from:
            previous, resume_session = resume_from
            prompt = build_resume_prompt(full, worker=worker, run=run, previous=previous)
            store.add_event(
                conn,
                run_id,
                "resume",
                f"Continuing the Claude session from attempt {previous['attempt']}",
                {"session_id": resume_session},
            )
        else:
            resume_session = None
            prompt = build_ticket_prompt(
                full,
                worker=worker,
                run=run,
                earlier_runs=earlier,
                worktree=str(path),
                branch=branch,
                base_sha=base_sha,
            )
        rules = build_rules(
            ticket_key=issue.key, owner_name=worker.get("owner_linear_name") or "the owner"
        )
        (log_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        (log_dir / "rules.md").write_text(rules, encoding="utf-8")
        import sys

        mcp = {
            "mcpServers": {
                "ticket": {
                    "command": sys.executable,
                    "args": [
                        "-m",
                        "pidgin.devwork.ticket_mcp",
                        "--db",
                        str(self._db_path),
                        "--run",
                        run_id,
                    ],
                }
            }
        }
        (log_dir / "mcp.json").write_text(json.dumps(mcp, indent=2), encoding="utf-8")

        exe = shutil.which("claude")
        if exe is None:
            raise RuntimeError("Claude Code CLI ('claude') not found on PATH")
        args = [
            exe,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--append-system-prompt-file",
            str(log_dir / "rules.md"),
            "--mcp-config",
            str(log_dir / "mcp.json"),
            "--max-turns",
            str(int(worker.get("max_turns") or 200)),
            "--disallowedTools",
            "Bash(git push:*)",
        ]
        if resume_session:
            args += ["--resume", resume_session]
        if worker.get("model"):
            args += ["--model", str(worker["model"])]
        if worker.get("permission_mode") == "bypass":
            args += ["--permission-mode", "bypassPermissions"]
        else:
            tools = [
                t.strip() for t in str(worker.get("allowed_tools") or "").split(",") if t.strip()
            ]
            args += ["--permission-mode", "acceptEdits", "--allowedTools", *tools, "mcp__ticket"]
        # Runs use the machine's logged-in Claude subscription, never API billing:
        # drop Pidgin's own API keys so `claude` can't pick them up.
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in (
                "CLAUDECODE",
                "CLAUDE_CODE_ENTRYPOINT",
                "CLAUDE_CODE_SSE_PORT",
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_AUTH_TOKEN",
                "ANTHROPIC_BASE_URL",
                "CLAUDE_CODE_USE_BEDROCK",
                "CLAUDE_CODE_USE_VERTEX",
            )
        }
        process = proc.spawn_detached(
            args,
            cwd=path,
            stdin_path=log_dir / "prompt.md",
            stdout_path=log_dir / "stream.jsonl",
            stderr_path=log_dir / "stderr.log",
            env=env,
        )
        self._procs[run_id] = process
        now = utc_now_iso()
        store.update_run(
            conn,
            run_id,
            status="running",
            pid=process.pid,
            process_started_at=proc.process_fingerprint(process.pid),
            started_at=now,
            heartbeat_at=now,
            last_output_at=now,
        )
        store.add_event(conn, run_id, "started", "Claude Code started")

    def _worktree_for_branch(self, repo: Path, branch: str) -> Path | None:
        out = _git(repo, "worktree", "list", "--porcelain", check=False)
        current: Path | None = None
        for line in out.splitlines():
            if line.startswith("worktree "):
                current = Path(line[len("worktree ") :])
            elif line.strip() == f"branch refs/heads/{branch}" and current is not None:
                return current
        return None

    # -- monitor -----------------------------------------------------------------------
    def _read_stream(self, conn: sqlite3.Connection, run: dict[str, Any]) -> dict[str, Any] | None:
        """Read new stream lines; returns the final result event if seen."""
        log_dir = run.get("log_dir")
        if not log_dir:
            return None
        path = Path(log_dir) / "stream.jsonl"
        if not path.exists():
            return None
        size = path.stat().st_size
        if size != self._sizes.get(run["id"]):
            self._sizes[run["id"]] = size
            store.update_run(conn, run["id"], last_output_at=utc_now_iso())
        result: dict[str, Any] | None = None
        offset = self._offsets.get(run["id"], 0)
        with open(path, "rb") as fh:
            fh.seek(offset)
            chunk = fh.read()
        end = chunk.rfind(b"\n")
        if end < 0:
            return None
        self._offsets[run["id"]] = offset + end + 1
        for raw in chunk[: end + 1].splitlines():
            try:
                evt = json.loads(raw)
            except ValueError:
                continue
            if (
                evt.get("type") == "system"
                and evt.get("subtype") == "init"
                and evt.get("session_id")
            ):
                store.update_run(conn, run["id"], session_id=evt["session_id"])
            elif evt.get("type") == "result":
                result = evt
        return result

    def _record_usage(self, conn: sqlite3.Connection, run_id: str, result: dict[str, Any]) -> None:
        usage = result.get("usage") or {}
        store.update_run(
            conn,
            run_id,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cache_read_tokens=usage.get("cache_read_input_tokens"),
            cache_write_tokens=usage.get("cache_creation_input_tokens"),
            cost_usd=result.get("total_cost_usd"),
            num_turns=result.get("num_turns"),
            session_id=result.get("session_id"),
        )
        denials = result.get("permission_denials") or []
        if denials:
            names = sorted({str(d.get("tool_name")) for d in denials})
            store.add_event(
                conn,
                run_id,
                "denied",
                f"{len(denials)} tool calls denied by permissions: {', '.join(names)}",
                {"denials": denials[:20]},
            )

    def _monitor(self, conn: sqlite3.Connection, run: dict[str, Any]) -> None:
        if run["id"] in self._preparing:
            return
        result = self._read_stream(conn, run)
        if result is not None:
            self._record_usage(conn, run["id"], result)
        worker = store.get_worker(conn, run["ai_employee_id"]) or {}
        popen = self._procs.get(run["id"])
        alive = (
            popen.poll() is None
            if popen is not None
            else proc.is_alive(run.get("pid"), run.get("process_started_at"))
        )
        store.update_run(conn, run["id"], heartbeat_at=utc_now_iso())
        fresh = store.get_run(conn, run["id"]) or run

        if fresh["stop_requested"]:
            if alive and run.get("pid"):
                proc.kill_tree(int(run["pid"]))
            self._finalize(conn, fresh, "cancelled", result)
            return
        if alive:
            started = _parse(fresh.get("started_at"))
            last_out = _parse(fresh.get("last_output_at"))
            limit = int(worker.get("time_limit_min") or 60)
            idle = int(worker.get("idle_limit_min") or 10)
            reason = None
            if started and (_now() - started).total_seconds() > limit * 60:
                reason = f"time limit after {limit} min"
            elif last_out and (_now() - last_out).total_seconds() > idle * 60:
                reason = f"no output for {idle} min"
            if reason:
                proc.kill_tree(int(fresh["pid"]))
                store.update_run(conn, run["id"], failure_reason=reason)
                self._finalize(conn, fresh, "timed_out", result)
            return
        # Process gone: read whatever is left of the stream, then finalize.
        if result is None:
            result = self._read_stream(conn, fresh)
            if result is not None:
                self._record_usage(conn, run["id"], result)
        exit_code = popen.returncode if popen is not None else None
        store.update_run(conn, run["id"], exit_code=exit_code)
        self._finalize(conn, store.get_run(conn, run["id"]) or fresh, "exited", result)

    # -- finalize ------------------------------------------------------------------------
    def _finalize(
        self, conn: sqlite3.Connection, run: dict[str, Any], how: str, result: dict[str, Any] | None
    ) -> None:
        self._procs.pop(run["id"], None)
        worker = store.get_worker(conn, run["ai_employee_id"]) or {}
        head = ""
        commits: list[str] = []
        if run.get("worktree_path") and Path(run["worktree_path"]).exists():
            head = _git(Path(run["worktree_path"]), "rev-parse", "HEAD", check=False)
            if run.get("base_sha"):
                commits = _git(
                    Path(run["worktree_path"]),
                    "log",
                    "--oneline",
                    f"{run['base_sha']}..HEAD",
                    check=False,
                ).splitlines()
        store.update_run(conn, run["id"], head_sha=head or None, ended_at=utc_now_iso())
        if commits:
            store.add_event(
                conn,
                run["id"],
                "commits",
                f"{len(commits)} commits on {run.get('branch')}",
                {"commits": commits[:30]},
            )
        outcome = run.get("outcome")

        try:
            client = linear_for_worker(conn, worker)
        except LinearError as exc:
            store.update_run(conn, run["id"], status="failed", failure_reason=str(exc))
            return

        if how == "cancelled":
            self._stop_ticket(conn, client, worker, run)
            return
        if outcome == "done":
            store.update_run(conn, run["id"], status="done")
            return
        if outcome in ("needs_owner", "blocked"):
            store.update_run(conn, run["id"], status="handed_off")
            return
        if how == "timed_out":
            self._fail(
                conn,
                run,
                f"Run timed out: {run.get('failure_reason') or 'limit reached'}",
                status="timed_out",
                commits=commits,
                client=client,
            )
            return
        subtype = (result or {}).get("subtype")
        if result is None or result.get("is_error") or subtype != "success":
            if subtype == "error_max_turns":
                why = f"turn limit ({worker.get('max_turns')}) reached"
            elif result is None:
                why = (
                    "Claude Code exited without a result"
                    + (
                        f" (exit code {run.get('exit_code')})"
                        if run.get("exit_code") is not None
                        else ""
                    )
                    + "; see stderr.log"
                )
            else:
                detail = str(result.get("result") or "").strip().splitlines()
                why = f"Claude Code ended with an error ({subtype})" + (
                    f": {detail[0][:300]}" if detail else ""
                )
                if "authenticate" in why.lower() or "login" in why.lower():
                    why += ". Log in again: run `claude` in a terminal on this computer and use /login."
            self._fail(conn, run, why, commits=commits, client=client)
            return
        # Clean exit but no hand-off: hand it to the owner so it never sits In Progress unowned.
        last_text = str(result.get("result") or "").strip()
        body = (
            "**Needs owner:** the run ended without a hand-off.\n\n"
            + (
                f"Its last message:\n\n> {last_text[:1500].replace(chr(10), chr(10) + '> ')}\n\n"
                if last_text
                else ""
            )
            + (
                f"- **Branch:** `{run.get('branch')}`, {len(commits)} commits (not pushed). Worktree: `{run.get('worktree_path')}`\n"
                if run.get("branch")
                else ""
            )
            + "Assign it back to me in Todo with a comment to continue."
        )
        try:
            meta = self._team_meta(client, worker)
            client.comment(run["ticket_id"], body)
            client.update_issue(
                run["ticket_id"],
                state_id=self._state_id(meta, worker, "needs_owner"),
                assignee_id=worker.get("owner_linear_id"),
            )
        except LinearError as exc:
            store.add_event(conn, run["id"], "error", f"Could not hand off in Linear: {exc}")
        store.update_run(
            conn, run["id"], status="ended_open", outcome_summary=last_text[:500] or None
        )
        store.add_event(conn, run["id"], "outcome", "Ended without a hand-off; handed to the owner")

    def _fail(
        self,
        conn: sqlite3.Connection,
        run: dict[str, Any],
        reason: str,
        *,
        status: str = "failed",
        claimed: bool = True,
        commits: list[str] | None = None,
        client: LinearClient | None = None,
    ) -> None:
        """Failure path (spec §5.5.7): comment, back to Todo, label runner-failed."""
        store.update_run(
            conn, run["id"], status=status, failure_reason=reason[:500], ended_at=utc_now_iso()
        )
        store.add_event(conn, run["id"], "failed", reason[:300])
        if not claimed:
            return
        worker = store.get_worker(conn, run["ai_employee_id"]) or {}
        try:
            client = client or linear_for_worker(conn, worker)
            meta = self._team_meta(client, worker)
            label_name = worker.get("rules", {}).get("failed_label", "runner-failed")
            label_id = client.ensure_label(label_name, worker["team_id"])
            issue = client.issue(run["ticket_id"])
            body = f"**Run failed:** {reason}."
            if run.get("branch"):
                body += f"\n\n- Branch kept: `{run['branch']}` ({len(commits or [])} commits). Worktree: `{run.get('worktree_path')}`"
            body += f"\n- Back in Todo with `{label_name}`. Remove the label (or press Retry in Pidgin) to try again."
            client.comment(issue.id, body)
            client.update_issue(
                issue.id,
                state_id=self._state_id(meta, worker, "todo"),
                label_ids=list({*issue.label_ids.values(), label_id}),
            )
        except LinearError as exc:
            store.add_event(
                conn, run["id"], "error", f"Could not report the failure in Linear: {exc}"
            )

    def _stop_ticket(
        self,
        conn: sqlite3.Connection,
        client: LinearClient,
        worker: dict[str, Any],
        run: dict[str, Any],
    ) -> None:
        store.update_run(conn, run["id"], status="cancelled")
        who = run.get("stopped_by") or "the owner"
        store.add_event(conn, run["id"], "cancelled", f"Stopped by {who}")
        if who == "Linear":
            return  # The owner already moved the ticket; don't fight it.
        try:
            meta = self._team_meta(client, worker)
            client.comment(
                run["ticket_id"],
                f"**Stopped** by {who} in Pidgin. Branch kept: `{run.get('branch')}`. "
                "It won't restart until the ticket is touched again (re-assign, edit or comment).",
            )
            client.update_issue(run["ticket_id"], state_id=self._state_id(meta, worker, "todo"))
            issue = client.issue(run["ticket_id"])
            store.update_run(conn, run["id"], ticket_updated_after_stop=issue.updated_at)
        except LinearError as exc:
            store.add_event(conn, run["id"], "error", f"Could not update Linear after stop: {exc}")

    # -- recovery ------------------------------------------------------------------------
    def _recover(self, conn: sqlite3.Connection) -> None:
        """Reconcile runs left from a previous process (spec §5.5.6)."""
        for run in store.active_runs(conn):
            if run["status"] in ("queued", "claiming", "preparing"):
                store.add_event(
                    conn, run["id"], "recovered", "Pidgin restarted; resuming preparation"
                )
                self._start_prepare(run["id"], recovering=True)
            elif run["status"] == "running":
                if proc.is_alive(run.get("pid"), run.get("process_started_at")):
                    store.add_event(
                        conn,
                        run["id"],
                        "recovered",
                        "Pidgin restarted; re-attached to the running process",
                    )
                else:
                    store.add_event(
                        conn, run["id"], "recovered", "Pidgin restarted; the process had ended"
                    )
        log.info("[devrunner] recovery pass done")


_runner: DevRunner | None = None


def get_runner() -> DevRunner | None:
    return _runner


def set_runner(runner: DevRunner | None) -> None:
    global _runner
    _runner = runner
