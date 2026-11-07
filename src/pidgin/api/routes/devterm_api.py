"""API for the Devs page: interactive Claude Code terminals the owner types into.

REST for the list (add, rename, remove, restart) and one WebSocket per
terminal carrying keystrokes in and PTY output out.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from pidgin.api.deps import require_workspace_session
from pidgin.devwork import terminals as dt

router = APIRouter(prefix="/{workspace_slug}/api/devs", tags=["devterm"])


class NewDevBody(BaseModel):
    name: str | None = None
    cwd: str | None = None


class DevPatchBody(BaseModel):
    name: str | None = None
    cwd: str | None = None


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
        "status": dt.manager().status(dev["id"]),
    }


@router.get("")
def api_devs(workspace_slug: str, request: Request) -> dict[str, Any]:
    session = require_workspace_session(request, workspace_slug)
    cwd = _default_cwd(session.conn)
    devs = dt.ensure_default_devs(session.conn, cwd)
    return {"devs": [_view(d) for d in devs], "default_cwd": cwd}


@router.post("")
def api_add_dev(workspace_slug: str, body: NewDevBody, request: Request) -> dict[str, Any]:
    session = require_workspace_session(request, workspace_slug)
    cwd = (body.cwd or "").strip() or _default_cwd(session.conn)
    if not Path(cwd).is_dir():
        raise HTTPException(status_code=400, detail=f"Folder not found: {cwd}")
    return _view(dt.create_dev(session.conn, cwd=cwd, name=(body.name or "").strip() or None))


@router.patch("/{dev_id}")
def api_patch_dev(
    workspace_slug: str, dev_id: str, body: DevPatchBody, request: Request
) -> dict[str, Any]:
    session = require_workspace_session(request, workspace_slug)
    dev = dt.get_dev(session.conn, dev_id)
    if dev is None:
        raise HTTPException(status_code=404, detail="Unknown dev")
    updates: dict[str, Any] = {}
    if body.name and body.name.strip():
        updates["name"] = body.name.strip()[:40]
    if body.cwd and body.cwd.strip() != dev["cwd"]:
        if not Path(body.cwd.strip()).is_dir():
            raise HTTPException(status_code=400, detail=f"Folder not found: {body.cwd}")
        # A Claude session belongs to its folder; a new folder means a new session.
        import uuid

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
            if msg.get("t") == "in":
                await asyncio.to_thread(term.write, str(msg.get("d") or ""))
            elif msg.get("t") == "resize":
                term.resize(int(msg.get("cols") or 120), int(msg.get("rows") or 32))
    except WebSocketDisconnect:
        pass
    finally:
        with term.lock:
            term.subs.discard(sub)
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sender
