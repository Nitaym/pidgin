"""API for the Devs page: interactive Claude Code terminals the owner types into.

REST for the list (add, rename, remove, restart) and one WebSocket per
terminal carrying keystrokes in and PTY output out.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from pidgin.api.deps import require_google_user, require_workspace_session
from pidgin.devwork import slots as dev_slots
from pidgin.devwork import store
from pidgin.devwork import terminals as dt
from pidgin.devwork.linear_api import LinearError
from pidgin.devwork.transcript import transcript
from pidgin.util.ids import utc_now_iso

router = APIRouter(prefix="/{workspace_slug}/api/devs", tags=["devterm"])


class NewDevBody(BaseModel):
    name: str | None = None
    cwd: str | None = None
    slot: str | None = None  # "auto" or "slot-N"; default follows the work_in setting


class DevPatchBody(BaseModel):
    name: str | None = None
    cwd: str | None = None
    slot: str | None = None  # "auto", "slot-N", or "" to leave the slot


class RunMessageBody(BaseModel):
    text: str


class SettingsBody(BaseModel):
    work_in: str | None = None
    slots_dir: str | None = None
    slots_repo: str | None = None
    max_slots: int | None = None


def _repo(conn: Any, settings: dict[str, str]) -> str:
    return settings.get("slots_repo") or _default_cwd(conn)


def _check_wanted(conn: Any, settings: dict[str, str], wanted: str | None) -> None:
    """Fail fast on a named slot that isn't free (cheap: no git fetch or checkout)."""
    if not wanted:
        return
    slot = next((s for s in dev_slots.list_slots(settings, dt.list_devs(conn)) if s["name"] == wanted), None)
    if slot is None:
        raise HTTPException(status_code=400, detail=f"No slot named {wanted}")
    if slot["state"] != "free":
        raise HTTPException(status_code=400, detail=f"{wanted} is in use ({slot['state']}: {slot['who']})")


def _into_slot(conn: Any, dev: dict[str, Any], wanted: str | None) -> None:
    """Point a dev at a slot (a new Claude session: sessions belong to a folder).

    Returns at once; the slot is made in the background while the terminal says so.
    """
    settings = dev_slots.get_settings(conn)
    _check_wanted(conn, settings, wanted)
    dt.manager().stop(dev["id"])
    dt.prepare_slot(conn, dev, settings, _repo(conn, settings), wanted)


def _out_of_slot(conn: Any, dev: dict[str, Any], cwd: str) -> None:
    dt.manager().stop(dev["id"])
    dt.update_dev(conn, dev["id"], slot=None, cwd=cwd, session_id=str(uuid.uuid4()))


def _default_cwd(conn: Any) -> str:
    row = conn.execute(
        "SELECT repo_path FROM dev_workers WHERE repo_path IS NOT NULL ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    return str(row["repo_path"]) if row and row["repo_path"] else str(Path.home())


def _view(dev: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": dev["id"],
        "name": dev["name"],
        "cwd": dev["cwd"],
        "session_id": dev["session_id"],
        "slot": dev.get("slot"),
        "status": dt.manager().status(dev["id"]),
    }


@router.get("")
def api_devs(workspace_slug: str, request: Request) -> dict[str, Any]:
    session = require_workspace_session(request, workspace_slug)
    conn = session.conn
    cwd = _default_cwd(conn)
    devs = dt.ensure_default_devs(conn, cwd)
    settings = dev_slots.get_settings(conn)
    return {
        "devs": [_view(d) for d in devs],
        "default_cwd": cwd,
        "settings": {**settings, "slots_repo": _repo(conn, settings)},
        "slots": dev_slots.list_slots(settings, devs),
    }


@router.put("/settings")
def api_dev_settings(workspace_slug: str, body: SettingsBody, request: Request) -> dict[str, Any]:
    """Where devs work. Switching to slots gives every dev its own slot; back moves them home."""
    session = require_workspace_session(request, workspace_slug)
    conn = session.conn
    updates = body.model_dump(exclude_none=True)
    if "work_in" in updates and updates["work_in"] not in ("folder", "slots"):
        raise HTTPException(status_code=400, detail="work_in must be folder or slots")
    if "max_slots" in updates:
        updates["max_slots"] = max(1, min(int(updates["max_slots"]), 16))
    before = dev_slots.get_settings(conn)
    if "slots_dir" in updates:
        updates["slots_dir"] = str(updates["slots_dir"]).strip().strip('"')
        if not updates["slots_dir"]:
            raise HTTPException(status_code=400, detail="Slots folder can't be empty")
        if updates["slots_dir"] != before["slots_dir"] and any(d.get("slot") for d in dt.list_devs(conn)):
            raise HTTPException(
                status_code=400, detail="Devs are working in slots: switch to Main folder first, then change the folder"
            )
    settings = dev_slots.set_settings(conn, updates)
    if settings["work_in"] == "slots" and before["work_in"] != "slots":
        for dev in dt.list_devs(conn):
            if not dev.get("slot"):
                _into_slot(conn, dev, None)
    elif settings["work_in"] == "folder" and before["work_in"] != "folder":
        home = _default_cwd(conn)
        for dev in dt.list_devs(conn):
            if dev.get("slot"):
                _out_of_slot(conn, dev, home)
    return api_devs(workspace_slug, request)


@router.post("")
def api_add_dev(workspace_slug: str, body: NewDevBody, request: Request) -> dict[str, Any]:
    session = require_workspace_session(request, workspace_slug)
    conn = session.conn
    settings = dev_slots.get_settings(conn)
    want_slot = body.slot if body.slot is not None else ("auto" if settings["work_in"] == "slots" and not body.cwd else "")
    name = (body.name or "").strip() or None
    if want_slot:
        wanted = None if want_slot == "auto" else want_slot
        _check_wanted(conn, settings, wanted)
        dev = dt.create_dev(conn, cwd=_default_cwd(conn), name=name)
        dt.prepare_slot(conn, dev, settings, _repo(conn, settings), wanted)
        return _view(dev)
    cwd = (body.cwd or "").strip() or _default_cwd(conn)
    if not Path(cwd).is_dir():
        raise HTTPException(status_code=400, detail=f"Folder not found: {cwd}")
    return _view(dt.create_dev(conn, cwd=cwd, name=name))


# -- ticket runs on the Devs page --------------------------------------------------
# Ticket runs stay headless (stream-json); the Devs page shows their transcript,
# takes messages into their live session, and can continue a finished one in a
# PTY terminal with `claude --resume`.


def _run_view(run: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in run.items() if k not in ("pid", "process_started_at")}
    from pidgin.devwork.runner import get_runner

    runner = get_runner()
    popen = runner._procs.get(run["id"]) if runner else None
    out["accepts_messages"] = bool(
        popen is not None and popen.stdin is not None and not popen.stdin.closed and popen.poll() is None
    )
    return out


@router.get("/runs")
def api_dev_runs(workspace_slug: str, request: Request) -> dict[str, Any]:
    """Active ticket runs, then finished ones from the last day not yet dismissed."""
    session = require_workspace_session(request, workspace_slug)
    conn = session.conn
    placeholders = ",".join("?" for _ in store.ACTIVE_STATUSES)
    rows = conn.execute(
        f"""SELECT * FROM code_runs
            WHERE status IN ({placeholders})
               OR (status != 'dropped' AND dismissed_at IS NULL AND ended_at >= ?)
            ORDER BY created_at DESC LIMIT 12""",
        [*store.ACTIVE_STATUSES, _day_ago()],
    ).fetchall()
    runs = [dict(r) for r in rows]
    runs.sort(key=lambda r: (r["status"] not in store.ACTIVE_STATUSES, r["created_at"]))
    return {
        "runs": [
            {
                "run": _run_view(r),
                "transcript": transcript(r.get("log_dir"), r.get("worktree_path"), limit=200),
            }
            for r in runs
        ]
    }


def _day_ago() -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(tz=UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _get_run(conn: Any, run_id: str) -> dict[str, Any]:
    run = store.get_run(conn, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run")
    return run


@router.post("/runs/{run_id}/message")
def api_dev_run_message(
    workspace_slug: str, run_id: str, body: RunMessageBody, request: Request
) -> dict[str, Any]:
    """Type into a running ticket run: into its live session, and onto the ticket."""
    from pidgin.devwork.runner import get_runner, linear_for_worker

    session = require_workspace_session(request, workspace_slug)
    user = require_google_user(request)
    conn = session.conn
    run = _get_run(conn, run_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Type a message first")
    who = (user.name or user.email or "The owner").split(" ")[0]
    runner = get_runner()
    if run["status"] != "running" or run.get("outcome") or runner is None:
        raise HTTPException(status_code=409, detail="This run isn't working any more")
    if not runner.send_message(run_id, f"{who} wrote in Pidgin:\n\n{text}"):
        raise HTTPException(
            status_code=409,
            detail="This run isn't taking messages (it's finishing, or it started before Pidgin restarted)",
        )
    store.add_event(conn, run_id, "message", f"{who} wrote in Pidgin: {text.splitlines()[0][:200]}", {"who": who, "body": text[:4000]})
    posted = True
    worker = store.get_worker(conn, run["ai_employee_id"]) or {}
    try:
        linear_for_worker(conn, worker).comment(run["ticket_id"], f"**{who} (in Pidgin):** {text}")
    except LinearError as exc:
        posted = False
        store.add_event(conn, run_id, "error", f"Could not copy the message to the ticket: {exc}")
    return {"status": "sent", "posted_to_ticket": posted}


@router.post("/runs/{run_id}/dismiss")
def api_dev_run_dismiss(workspace_slug: str, run_id: str, request: Request) -> dict[str, str]:
    session = require_workspace_session(request, workspace_slug)
    run = _get_run(session.conn, run_id)
    if run["status"] in store.ACTIVE_STATUSES:
        raise HTTPException(status_code=400, detail="Stop the run first")
    store.update_run(session.conn, run_id, dismissed_at=utc_now_iso())
    return {"status": "ok"}


@router.post("/runs/{run_id}/continue")
def api_dev_run_continue(workspace_slug: str, run_id: str, request: Request) -> dict[str, Any]:
    """Pick a finished run up by hand: a dev terminal in its folder, resuming its session."""
    session = require_workspace_session(request, workspace_slug)
    conn = session.conn
    run = _get_run(conn, run_id)
    if run["status"] in store.ACTIVE_STATUSES:
        raise HTTPException(status_code=400, detail="The run is still working; stop it first")
    cwd = run.get("worktree_path") or ""
    if not cwd or not Path(cwd).is_dir():
        raise HTTPException(status_code=400, detail="The run's folder is gone")
    if not run.get("session_id"):
        raise HTTPException(status_code=400, detail="The run has no Claude session to continue")
    settings = dev_slots.get_settings(conn)
    slot = None
    if str(Path(cwd).parent).lower() == str(Path(settings["slots_dir"])).lower():
        slot = Path(cwd).name
        state = next((s for s in dev_slots.list_slots(settings, dt.list_devs(conn)) if s["name"] == slot), None)
        if state and state["state"] != "free":
            raise HTTPException(status_code=409, detail=f"{slot} is in use ({state['state']}: {state['who']})")
    dev = dt.create_dev(conn, cwd=cwd, name=f"{run['ticket_key']} (continued)"[:40], slot=slot)
    dt.update_dev(conn, dev["id"], session_id=run["session_id"])
    store.update_run(conn, run_id, dismissed_at=utc_now_iso())
    fresh = dt.get_dev(conn, dev["id"])
    assert fresh is not None
    return _view(fresh)


@router.patch("/{dev_id}")
def api_patch_dev(
    workspace_slug: str, dev_id: str, body: DevPatchBody, request: Request
) -> dict[str, Any]:
    session = require_workspace_session(request, workspace_slug)
    dev = dt.get_dev(session.conn, dev_id)
    if dev is None:
        raise HTTPException(status_code=404, detail="Unknown dev")
    if body.slot is not None:
        if body.slot:
            _into_slot(session.conn, dev, None if body.slot == "auto" else body.slot)
        elif dev.get("slot"):
            _out_of_slot(session.conn, dev, (body.cwd or "").strip() or _default_cwd(session.conn))
        dev = dt.get_dev(session.conn, dev_id)
        assert dev is not None
    updates: dict[str, Any] = {}
    if body.name and body.name.strip():
        updates["name"] = body.name.strip()[:40]
    if body.slot is None and body.cwd and body.cwd.strip() != dev["cwd"]:
        if not Path(body.cwd.strip()).is_dir():
            raise HTTPException(status_code=400, detail=f"Folder not found: {body.cwd}")
        # A Claude session belongs to its folder; a new folder means a new session.
        updates.update(cwd=body.cwd.strip(), session_id=str(uuid.uuid4()))
    dt.update_dev(session.conn, dev_id, **updates)
    if "cwd" in updates:
        dt.manager().stop(dev_id)
    dev = dt.get_dev(session.conn, dev_id)
    assert dev is not None
    return _view(dev)


@router.delete("/{dev_id}")
def api_remove_dev(workspace_slug: str, dev_id: str, request: Request) -> dict[str, str]:
    session = require_workspace_session(request, workspace_slug)
    dt.manager().stop(dev_id)
    dt.archive_dev(session.conn, dev_id)
    return {"status": "ok"}


@router.post("/{dev_id}/restart")
def api_restart_dev(workspace_slug: str, dev_id: str, request: Request) -> dict[str, Any]:
    session = require_workspace_session(request, workspace_slug)
    dev = dt.get_dev(session.conn, dev_id)
    if dev is None:
        raise HTTPException(status_code=404, detail="Unknown dev")
    dt.manager().restart(dev)
    return _view(dev)


def _same_origin(ws: WebSocket) -> bool:
    """Only Pidgin's own pages may open a terminal (it is a full shell)."""
    origin = ws.headers.get("origin")
    if not origin:
        return False
    host = ws.headers.get("host", "")
    parsed = urlparse(origin)
    if parsed.netloc == host:
        return True
    # The Vite dev server proxies to us from its own port on localhost.
    return parsed.hostname in ("127.0.0.1", "localhost") and host.split(":")[0] in (
        "127.0.0.1",
        "localhost",
    )


@router.websocket("/{dev_id}/ws")
async def ws_dev_terminal(websocket: WebSocket, workspace_slug: str, dev_id: str) -> None:
    if not _same_origin(websocket):
        await websocket.close(code=4403)
        return
    try:
        session = require_workspace_session(websocket, workspace_slug)  # type: ignore[arg-type]
    except HTTPException:
        await websocket.close(code=4401)
        return
    dev = dt.get_dev(session.conn, dev_id)
    session.conn.close()
    if dev is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()

    cols = int(websocket.query_params.get("cols") or 120)
    rows = int(websocket.query_params.get("rows") or 32)
    term = dt.manager().get(dev, start=False)
    term.resize(cols, rows)
    cols, rows = term.cols, term.rows  # clamped
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    sub = (loop, queue)
    with term.lock:
        backlog = term.buffer.decode("utf-8", errors="replace")
        term.subs.add(sub)
    if term.proc is None and term.exit_note is None:
        await asyncio.to_thread(term.start)

    async def pump_out() -> None:
        if backlog:
            await websocket.send_text(backlog)
        while True:
            chunk = await queue.get()
            if chunk is None:
                return
            # Coalesce whatever else is already waiting into one frame.
            parts = [chunk]
            while not queue.empty() and len(parts) < 64:
                nxt = queue.get_nowait()
                if nxt is None:
                    break
                parts.append(nxt)
            await websocket.send_text("".join(parts))

    sender = asyncio.create_task(pump_out())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            # Several windows can show one terminal; the PTY takes the size of
            # the one being used (typed in, focused or resized) most recently.
            if msg.get("t") == "in":
                if (term.cols, term.rows) != (cols, rows):
                    term.resize(cols, rows)
                await asyncio.to_thread(term.write, str(msg.get("d") or ""))
            elif msg.get("t") == "resize":
                cols, rows = int(msg.get("cols") or 120), int(msg.get("rows") or 32)
                term.resize(cols, rows)
                cols, rows = term.cols, term.rows
    except WebSocketDisconnect:
        pass
    finally:
        with term.lock:
            term.subs.discard(sub)
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sender
