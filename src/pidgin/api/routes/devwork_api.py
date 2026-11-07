"""API for the Developer Worker: setup, work dashboard, runs, Stop/Retry.

See specs/DEVELOPER_WORKER_SPEC.html §4.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from pidgin.api.deps import require_google_user, require_workspace_session
from pidgin.db.employees import get_agent_by_handle
from pidgin.devwork import store
from pidgin.devwork.linear_api import LinearClient, LinearError
from pidgin.devwork.runner import (
    RUNNING_CHECK_SECONDS,
    check_repo,
    get_runner,
    linear_for_worker,
)
from pidgin.devwork.transcript import transcript
from pidgin.util.ids import utc_now_iso

router = APIRouter(prefix="/{workspace_slug}/api/dev", tags=["devwork"])


class WorkerConfigBody(BaseModel):
    enabled: bool | None = None
    linear_installation_id: str | None = None
    team_id: str | None = None
    team_key: str | None = None
    owner_linear_id: str | None = None
    owner_linear_name: str | None = None
    repo_path: str | None = None
    base_branch: str | None = None
    worktree_root: str | None = None
    setup_command: str | None = None
    branch_pattern: str | None = None
    max_concurrent: int | None = None
    time_limit_min: int | None = None
    idle_limit_min: int | None = None
    max_turns: int | None = None
    poll_seconds: int | None = None
    model: str | None = None
    permission_mode: str | None = None
    allowed_tools: str | None = None
    rules: dict[str, Any] | None = None
    status_map: dict[str, str] | None = None


class RepoCheckBody(BaseModel):
    path: str
    base_branch: str = "main"


class EnrichBody(BaseModel):
    key: str


class StopBody(BaseModel):
    reason: str | None = None


def _agent(conn: sqlite3.Connection, handle: str) -> dict[str, Any]:
    agent = get_agent_by_handle(conn, handle)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown agent")
    return agent


def _is_developer(conn: sqlite3.Connection, agent: dict[str, Any]) -> bool:
    row = conn.execute(
        "SELECT recipe_id FROM ai_employee_recipe_snapshots WHERE id = ?",
        (agent.get("recipe_snapshot_id"),),
    ).fetchone()
    if row is not None and row["recipe_id"] == "developer":
        return True
    return store.get_worker(conn, agent["id"]) is not None


def _client_for_installation(conn: sqlite3.Connection, installation_id: str) -> LinearClient:
    row = conn.execute(
        "SELECT credentials_json, connector_type FROM connector_installations WHERE id = ?",
        (installation_id,),
    ).fetchone()
    if row is None or row["connector_type"] != "linear":
        raise HTTPException(status_code=404, detail="Unknown Linear connection")
    key = json.loads(row["credentials_json"] or "{}").get("fields", {}).get("api_key", "")
    return LinearClient(key)


def _run_view(run: dict[str, Any]) -> dict[str, Any]:
    out = dict(run)
    out.pop("pid", None)
    out.pop("process_started_at", None)
    return out


@router.get("/{handle}")
def api_dev_summary(workspace_slug: str, handle: str, request: Request) -> dict[str, Any]:
    session = require_workspace_session(request, workspace_slug)
    conn = session.conn
    agent = _agent(conn, handle)
    if not _is_developer(conn, agent):
        raise HTTPException(status_code=404, detail="Not a developer")
    worker = store.ensure_worker(conn, agent["id"], handle)
    runs = store.runs_for_agent(conn, agent["id"], limit=40)
    active = [r for r in runs if r["status"] in store.ACTIVE_STATUSES]
    recent = [
        r for r in runs if r["status"] not in store.ACTIVE_STATUSES and r["status"] != "dropped"
    ]
    day = conn.execute(
        """SELECT COALESCE(SUM(cost_usd), 0) AS cost,
                  COALESCE(SUM(COALESCE(input_tokens,0) + COALESCE(output_tokens,0)
                               + COALESCE(cache_read_tokens,0) + COALESCE(cache_write_tokens,0)), 0) AS tokens,
                  SUM(CASE WHEN status IN ('failed','timed_out') THEN 1 ELSE 0 END) AS failed
           FROM code_runs WHERE ai_employee_id = ? AND created_at >= datetime('now', '-1 day')""",
        (agent["id"],),
    ).fetchone()
    installations = [
        dict(r)
        for r in conn.execute(
            "SELECT id, display_name, status, config_json FROM connector_installations WHERE connector_type = 'linear'"
        ).fetchall()
    ]
    return {
        "agent": {
            k: agent[k] for k in ("id", "handle", "display_name", "role_title", "current_status")
        },
        "worker": worker,
        "linear_installations": installations,
        "active": [_run_view(r) for r in active],
        "recent": [_run_view(r) for r in recent[:25]],
        "stats": {
            "running": len([r for r in active if r["status"] == "running"]),
            "active": len(active),
            "queued": len(
                [
                    q
                    for q in worker["queue"]
                    if q["reason"]
                    in ("Waiting for a free slot", "Waits until no assigned ticket is waiting")
                ]
            ),
            "handed_off": len([r for r in recent if r["status"] in ("handed_off", "ended_open")]),
            "failed_24h": int(day["failed"] or 0),
            "cost_24h": float(day["cost"] or 0),
            "tokens_24h": int(day["tokens"] or 0),
        },
        "runner_alive": get_runner() is not None,
        "polling": _polling(agent["id"], worker),
    }


def _polling(ai_employee_id: str, worker: dict[str, Any]) -> dict[str, Any]:
    """How often the runner checks Linear and what Linear's rate headers last said."""
    base = max(
        store.MIN_POLL_SECONDS,
        min(int(worker.get("poll_seconds") or store.DEFAULT_POLL_SECONDS), store.MAX_POLL_SECONDS),
    )
    runner = get_runner()
    state = (runner.poll_state(ai_employee_id) if runner else None) or {}
    return {
        "every": state.get("every", base),
        "base": base,
        "running_check_every": RUNNING_CHECK_SECONDS,
        **{k: v for k, v in state.items() if k not in ("every", "base")},
    }


@router.get("/{handle}/terminals")
def api_dev_terminals(workspace_slug: str, handle: str, request: Request) -> dict[str, Any]:
    """Live Claude Code terminals: every active run, then the latest finished ones."""
    session = require_workspace_session(request, workspace_slug)
    conn = session.conn
    agent = _agent(conn, handle)
    runs = store.runs_for_agent(conn, agent["id"], limit=20)
    active = [r for r in runs if r["status"] in store.ACTIVE_STATUSES and r["status"] != "queued"]
    finished = [
        r for r in runs if r["status"] not in store.ACTIVE_STATUSES and r["status"] != "dropped"
    ]
    shown = active + finished[: max(0, 2 - len(active))]
    return {
        "terminals": [
            {
                "run": _run_view(r),
                "transcript": transcript(r.get("log_dir"), r.get("worktree_path"), limit=120),
            }
            for r in shown
        ]
    }


@router.put("/{handle}/config")
def api_dev_config(
    workspace_slug: str, handle: str, body: WorkerConfigBody, request: Request
) -> dict[str, Any]:
    session = require_workspace_session(request, workspace_slug)
    conn = session.conn
    agent = _agent(conn, handle)
    store.ensure_worker(conn, agent["id"], handle)
    updates = body.model_dump(exclude_none=True)
    if "enabled" in updates:
        updates["enabled"] = 1 if updates["enabled"] else 0
    if "permission_mode" in updates and updates["permission_mode"] not in ("allowlist", "bypass"):
        raise HTTPException(status_code=400, detail="permission_mode must be allowlist or bypass")
    if "max_concurrent" in updates:
        updates["max_concurrent"] = max(1, min(int(updates["max_concurrent"]), 8))
    if "poll_seconds" in updates:
        updates["poll_seconds"] = max(
            store.MIN_POLL_SECONDS, min(int(updates["poll_seconds"]), store.MAX_POLL_SECONDS)
        )
    if "linear_installation_id" in updates:
        updates["viewer_id"] = None  # re-resolve who the key belongs to on the next poll
        try:
            info = _client_for_installation(conn, updates["linear_installation_id"]).viewer()
            updates["viewer_id"] = info["viewer"].get("id")
            updates["viewer_name"] = info["viewer"].get("name")
        except LinearError:
            pass
    if "rules" in updates:
        current = store.get_worker(conn, agent["id"]) or {}
        before = current.get("rules", {})
        updates["rules"] = {**before, **updates["rules"]}
        if updates["rules"].get("enrich") and not before.get("enrich"):
            # Switching enrichment on: only tickets that enter Todo from now on.
            updates["rules"]["enrich_since"] = utc_now_iso()
        if "max_enrich" in updates["rules"]:
            updates["rules"]["max_enrich"] = max(1, min(int(updates["rules"]["max_enrich"] or 2), 6))
    if "status_map" in updates:
        current = store.get_worker(conn, agent["id"]) or {}
        updates["status_map"] = {**current.get("status_map", {}), **updates["status_map"]}
    store.update_worker(conn, agent["id"], updates)
    if updates.get("enabled") == 1:
        store.update_worker(conn, agent["id"], {"last_poll_at": None})
    return store.get_worker(conn, agent["id"]) or {}


@router.post("/{handle}/enrich")
def api_dev_enrich(workspace_slug: str, handle: str, body: EnrichBody, request: Request) -> dict[str, Any]:
    """Push one Todo ticket into enrichment, whenever it entered Todo."""
    session = require_workspace_session(request, workspace_slug)
    conn = session.conn
    agent = _agent(conn, handle)
    worker = store.get_worker(conn, agent["id"])
    if worker is None or not worker.get("linear_installation_id"):
        raise HTTPException(status_code=400, detail="Set up Linear first")
    if not worker["rules"].get("enrich"):
        raise HTTPException(status_code=400, detail="Switch on enrichment first")
    key = body.key.strip().upper()
    try:
        issue = linear_for_worker(conn, worker).issue(key)
    except LinearError as exc:
        raise HTTPException(status_code=404, detail=f"{key}: {exc}") from exc
    todo = worker["status_map"].get("todo", "Todo")
    if issue.state_name.lower() != todo.lower():
        raise HTTPException(status_code=400, detail=f"{key} is in {issue.state_name}, not {todo}")
    if worker.get("owner_linear_id") and issue.assignee_id == worker["owner_linear_id"]:
        raise HTTPException(status_code=400, detail=f"{key} is assigned to you; assign it to Claude or unassign it")
    pushed = [x for x in worker["rules"].get("enrich_push") or [] if x != issue.id] + [issue.id]
    store.update_worker(
        conn, agent["id"], {"rules": {**worker["rules"], "enrich_push": pushed}, "last_poll_at": None}
    )
    return {"status": "queued", "key": issue.key, "title": issue.title}


@router.post("/{handle}/poll-now")
def api_dev_poll_now(workspace_slug: str, handle: str, request: Request) -> dict[str, str]:
    session = require_workspace_session(request, workspace_slug)
    agent = _agent(session.conn, handle)
    store.update_worker(session.conn, agent["id"], {"last_poll_at": None})
    return {"status": "ok"}


@router.get("/linear/{installation_id}/teams")
def api_dev_linear_teams(
    workspace_slug: str, installation_id: str, request: Request
) -> dict[str, Any]:
    session = require_workspace_session(request, workspace_slug)
    try:
        return _client_for_installation(session.conn, installation_id).viewer()
    except LinearError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/linear/{installation_id}/teams/{team_id}")
def api_dev_linear_team(
    workspace_slug: str, installation_id: str, team_id: str, request: Request
) -> dict[str, Any]:
    session = require_workspace_session(request, workspace_slug)
    try:
        return _client_for_installation(session.conn, installation_id).team_meta(team_id)
    except LinearError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/repo-check")
def api_dev_repo_check(
    workspace_slug: str, body: RepoCheckBody, request: Request
) -> dict[str, Any]:
    require_workspace_session(request, workspace_slug)
    return check_repo(body.path, body.base_branch)


def _stream_lines(log_dir: str | None, limit: int = 400) -> list[dict[str, Any]]:
    """Render Claude Code's stream-json into readable log lines."""
    if not log_dir:
        return []
    path = Path(log_dir) / "stream.jsonl"
    if not path.exists():
        return []
    lines: list[dict[str, Any]] = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                evt = json.loads(raw)
            except ValueError:
                continue
            kind = evt.get("type")
            if kind == "assistant":
                for block in (evt.get("message") or {}).get("content", []):
                    if block.get("type") == "text" and block.get("text", "").strip():
                        lines.append({"kind": "text", "text": block["text"].strip()})
                    elif block.get("type") == "tool_use":
                        inp = block.get("input") or {}
                        detail = (
                            inp.get("command")
                            or inp.get("file_path")
                            or inp.get("pattern")
                            or inp.get("description")
                            or inp.get("body")
                            or inp.get("summary")
                            or ""
                        )
                        name = str(block.get("name", "")).replace("mcp__ticket__", "ticket.")
                        lines.append(
                            {"kind": "tool", "text": f"{name} {str(detail)[:200]}".strip()}
                        )
            elif kind == "user":
                for block in (
                    (evt.get("message") or {}).get("content", [])
                    if isinstance((evt.get("message") or {}).get("content"), list)
                    else []
                ):
                    if block.get("type") == "tool_result" and block.get("is_error"):
                        content = block.get("content")
                        text = content if isinstance(content, str) else json.dumps(content)[:300]
                        lines.append({"kind": "error", "text": str(text)[:300]})
            elif kind == "result":
                lines.append(
                    {
                        "kind": "result",
                        "text": f"Finished: {evt.get('subtype')} · {evt.get('num_turns')} turns · ${evt.get('total_cost_usd', 0):.2f}",
                    }
                )
            elif kind == "system" and evt.get("subtype") == "init":
                lines.append(
                    {
                        "kind": "system",
                        "text": f"Session {evt.get('session_id', '')[:8]} · model {evt.get('model', '?')}",
                    }
                )
    return lines[-limit:]


@router.get("/runs/{run_id}")
def api_dev_run(workspace_slug: str, run_id: str, request: Request) -> dict[str, Any]:
    session = require_workspace_session(request, workspace_slug)
    run = store.get_run(session.conn, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run")
    agent = session.conn.execute(
        "SELECT handle, display_name FROM ai_employees WHERE id = ?", (run["ai_employee_id"],)
    ).fetchone()
    stderr = ""
    if run.get("log_dir") and (Path(run["log_dir"]) / "stderr.log").exists():
        stderr = (Path(run["log_dir"]) / "stderr.log").read_text(
            encoding="utf-8", errors="replace"
        )[-4000:]
    return {
        "run": _run_view(run),
        "agent": dict(agent) if agent else None,
        "events": store.run_events(session.conn, run_id),
        "log": _stream_lines(run.get("log_dir")),
        "transcript": transcript(run.get("log_dir"), run.get("worktree_path")),
        "stderr": stderr,
    }


@router.post("/runs/{run_id}/stop")
def api_dev_run_stop(
    workspace_slug: str, run_id: str, body: StopBody, request: Request
) -> dict[str, str]:
    session = require_workspace_session(request, workspace_slug)
    user = require_google_user(request)
    run = store.get_run(session.conn, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run")
    if run["status"] not in store.ACTIVE_STATUSES:
        raise HTTPException(status_code=400, detail="Run is not active")
    who = user.name or user.email
    store.update_run(session.conn, run_id, stop_requested=1, stopped_by=who)
    store.add_event(
        session.conn,
        run_id,
        "stop",
        f"Stop requested by {who}" + (f": {body.reason}" if body.reason else ""),
    )
    return {"status": "stopping"}


@router.post("/runs/{run_id}/retry")
def api_dev_run_retry(workspace_slug: str, run_id: str, request: Request) -> dict[str, str]:
    """Remove runner-failed in Linear and poll now; the ticket is picked up again."""
    session = require_workspace_session(request, workspace_slug)
    conn = session.conn
    run = store.get_run(conn, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run")
    worker = store.get_worker(conn, run["ai_employee_id"])
    if worker is None:
        raise HTTPException(status_code=400, detail="No developer config")
    try:
        client = linear_for_worker(conn, worker)
        issue = client.issue(run["ticket_id"])
        client.remove_label(issue, worker["rules"].get("failed_label", "runner-failed"))
        if run["status"] == "cancelled":
            client.comment(issue.id, "Retrying from Pidgin.")
    except LinearError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.add_event(
        conn, run_id, "retry", "Retry requested; the ticket will be picked up on the next poll"
    )
    store.update_worker(conn, run["ai_employee_id"], {"last_poll_at": None})
    return {"status": "ok"}
