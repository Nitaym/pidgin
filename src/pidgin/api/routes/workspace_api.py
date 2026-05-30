from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from pidgin.api.deps import require_workspace_session
from pidgin.db.chat import get_or_create_room_conversation, list_messages, list_rooms
from pidgin.db.diagnostics import get_turn, list_audit_log, list_inbound_events, list_turns
from pidgin.db.employees import list_agents
from pidgin.hire import HireError, hire_support_agent
from pidgin.services import inject_test_event
from pidgin.services.admin import process_pending_events
from pidgin.services.chat import send_chat_message

router = APIRouter(prefix="/{workspace_slug}/api", tags=["workspace"])


class InjectEventBody(BaseModel):
    message: str = Field(default="API test event", min_length=1)


class SendMessageBody(BaseModel):
    body: str = Field(min_length=1)
    agent_handle: str = Field(default="support")


@router.get("/agents")
def api_list_agents(workspace_slug: str, request: Request) -> list[dict]:
    session = require_workspace_session(request, workspace_slug)
    return list_agents(session.conn)


@router.get("/rooms")
def api_list_rooms(workspace_slug: str, request: Request) -> list[dict]:
    session = require_workspace_session(request, workspace_slug)
    return list_rooms(session.conn)


@router.post("/hire")
def api_hire_support(workspace_slug: str, request: Request) -> dict[str, str]:
    session = require_workspace_session(request, workspace_slug)
    try:
        return hire_support_agent(session.conn, paths_root=session.paths_root)
    except HireError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/rooms/{room_id}/messages")
def api_room_messages(workspace_slug: str, room_id: str, request: Request) -> dict:
    session = require_workspace_session(request, workspace_slug)
    room = session.conn.execute("SELECT id FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    conversation_id = get_or_create_room_conversation(session.conn, room_id)
    return {
        "conversation_id": conversation_id,
        "messages": list_messages(session.conn, conversation_id),
    }


@router.post("/rooms/{room_id}/messages")
def api_send_room_message(
    workspace_slug: str,
    room_id: str,
    body: SendMessageBody,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    room = session.conn.execute("SELECT id FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    try:
        message_id, event_id = send_chat_message(
            session.conn,
            room_id=room_id,
            body_text=body.body,
            agent_handle=body.agent_handle,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    conversation_id = get_or_create_room_conversation(session.conn, room_id)
    return {
        "message_id": message_id,
        "event_id": event_id,
        "conversation_id": conversation_id,
        "messages": list_messages(session.conn, conversation_id),
    }


@router.post("/inject-event")
def api_inject_event(
    workspace_slug: str,
    body: InjectEventBody,
    request: Request,
) -> dict[str, str]:
    session = require_workspace_session(request, workspace_slug)
    event_id = inject_test_event(session.conn, message=body.message)
    return {"event_id": event_id}


@router.post("/run-once")
def api_run_once(workspace_slug: str, request: Request) -> dict[str, int]:
    session = require_workspace_session(request, workspace_slug)
    processed = process_pending_events(session.conn)
    return {"processed": processed}


@router.get("/health")
def api_workspace_health(workspace_slug: str, request: Request) -> dict[str, str | int]:
    session = require_workspace_session(request, workspace_slug)
    pending = session.conn.execute(
        "SELECT COUNT(*) AS n FROM inbound_events WHERE processing_status = 'pending'"
    ).fetchone()
    turns = session.conn.execute("SELECT COUNT(*) AS n FROM turns").fetchone()
    return {
        "workspace_id": session.workspace_id,
        "slug": session.slug,
        "display_name": session.display_name,
        "pending_events": int(pending["n"]) if pending else 0,
        "turn_count": int(turns["n"]) if turns else 0,
    }


@router.get("/events")
def api_list_events(workspace_slug: str, request: Request, limit: int = 50) -> list[dict]:
    session = require_workspace_session(request, workspace_slug)
    return list_inbound_events(session.conn, limit=limit)


@router.get("/turns")
def api_list_turns(workspace_slug: str, request: Request, limit: int = 50) -> list[dict]:
    session = require_workspace_session(request, workspace_slug)
    return list_turns(session.conn, limit=limit)


@router.get("/turns/{turn_id}")
def api_get_turn(workspace_slug: str, turn_id: str, request: Request) -> dict:
    session = require_workspace_session(request, workspace_slug)
    detail = get_turn(session.conn, turn_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    return detail


@router.get("/audit")
def api_list_audit(workspace_slug: str, request: Request, limit: int = 100) -> list[dict]:
    session = require_workspace_session(request, workspace_slug)
    return list_audit_log(session.conn, limit=limit)
