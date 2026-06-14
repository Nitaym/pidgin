from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from pidgin.api.deps import (
    OAUTH_STATE_SESSION_KEY,
    require_workspace_session,
)
from pidgin.db import connect
from pidgin.db.chat import (
    ensure_agent_conversation,
    get_agent_conversation,
    get_or_create_agent_conversation,
    list_messages,
)
from pidgin.db.diagnostics import (
    get_turn,
    list_audit_log,
    list_inbound_events,
    list_model_invocations,
    list_turns,
)
from pidgin.db.employees import get_agent_by_handle, list_agents
from pidgin.db.principals import get_or_create_operator_principal
from pidgin.hire import HireError, TemplateHireRequest, hire_support_agent, hire_with_template
from pidgin.hr_assist import (
    HrAssistError,
    create_session,
    get_session,
    send_operator_message,
)
from pidgin.hr_assist import (
    list_messages as list_hr_assist_messages,
)
from pidgin.llm.types import StreamEvent
from pidgin.recipes.catalog import (
    UnknownRecipeError,
    bundled_template_detail,
    list_bundled_template_summaries,
)
from pidgin.runtime.prompt import build_system_prompt
from pidgin.runtime.streaming import KeyedTurnEventSink, format_sse, turn_event_bus
from pidgin.runtime.turn_dispatcher import dispatch_turn
from pidgin.services import inject_test_event
from pidgin.services.admin import process_pending_events
from pidgin.services.agent_lifecycle import ArchiveError, archive_agent
from pidgin.services.brief import (
    BriefError,
    create_template_from_agent,
    duplicate_bundled_template,
    update_agent_brief,
)
from pidgin.services.chat import send_chat_message
from pidgin.services.common_instructions import (
    DEFAULT_COMMON_INSTRUCTIONS,
    CommonInstructionsError,
    common_instructions_text,
    get_common_instructions,
    save_common_instructions,
)
from pidgin.services.integrations import (
    IntegrationError,
    connect_manual,
    disconnect,
    get_integration_catalog,
    list_integrations,
    run_health_check,
    start_oauth,
    update_integration_config,
)
from pidgin.templates import (
    TemplateError,
    create_workspace_template,
    delete_workspace_template,
    get_workspace_template,
    is_archived,
    list_workspace_template_summaries,
    load_archived,
    save_workspace_template_version,
    set_archived,
)
from pidgin.types.customization import HireCustomization, IdealCandidate, JobRequirements
from pidgin.types.enums import ProcessingStatus
from pidgin.workspace.factory import build_workspace_context_from_conn
from pidgin.workspace.manager import WorkspacePaths

router = APIRouter(prefix="/{workspace_slug}/api", tags=["workspace"])


class InjectEventBody(BaseModel):
    message: str = Field(default="API test event", min_length=1)


class SendMessageBody(BaseModel):
    body: str = Field(min_length=1)


class HireCustomizationBody(BaseModel):
    job_requirements: JobRequirements = Field(default_factory=JobRequirements)
    ideal_candidate: IdealCandidate = Field(default_factory=IdealCandidate)
    your_take: str = ""
    gender: str = ""
    voice: str = ""


class HireBody(BaseModel):
    template_source: str = Field(default="bundled")
    template_id: str | None = None
    slug: str | None = None
    version: int | None = None
    customization: HireCustomizationBody | None = None
    display_name: str | None = None
    handle: str | None = None
    manager_principal_id: str | None = None


class CreateWorkspaceTemplateBody(BaseModel):
    name: str = Field(min_length=1)
    slug: str | None = None
    customization: HireCustomizationBody | None = None
    duplicate_from_recipe_id: str | None = None


class PatchWorkspaceTemplateBody(BaseModel):
    name: str | None = None
    customization: HireCustomizationBody


class CreateTemplateFromAgentBody(BaseModel):
    name: str = Field(min_length=1)
    slug: str | None = None


class ArchiveProfileBody(BaseModel):
    source: str = Field(pattern="^(bundled|workspace)$")
    id: str = Field(min_length=1)
    archived: bool


class CandidateFinderTurn(BaseModel):
    role: str = Field(pattern="^(operator|assist)$")
    text: str


class CandidateFinderBody(BaseModel):
    message: str = Field(min_length=1)
    history: list[CandidateFinderTurn] = Field(default_factory=list)


class CommonInstructionsBody(BaseModel):
    body_markdown: str = Field(min_length=1)


class CreateHrAssistSessionBody(BaseModel):
    context_type: str = Field(pattern="^(hire|agent|template)$")
    context_id: str = Field(min_length=1)


class HrAssistMessageBody(BaseModel):
    body_text: str = Field(min_length=1)
    customization: HireCustomizationBody | None = None


class ManualConnectBody(BaseModel):
    display_name: str = Field(min_length=1)
    fields: dict[str, str] = Field(default_factory=dict)


class OAuthStartBody(BaseModel):
    display_name: str | None = None


class IntegrationConfigBody(BaseModel):
    config: dict[str, str] = Field(default_factory=dict)


@router.get("/agents")
def api_list_agents(workspace_slug: str, request: Request) -> list[dict]:
    session = require_workspace_session(request, workspace_slug)
    agents = list_agents(session.conn)
    for agent in agents:
        conversation = get_agent_conversation(session.conn, agent["handle"])
        if conversation is not None:
            agent["conversation_id"] = conversation["id"]
        else:
            agent["conversation_id"] = None
    return agents


@router.get("/role-templates")
def api_list_role_templates(workspace_slug: str, request: Request) -> dict:
    session = require_workspace_session(request, workspace_slug)
    root = Path(session.paths_root)
    archived = load_archived(root)
    bundled = list_bundled_template_summaries()
    for entry in bundled:
        entry["archived"] = is_archived(archived, "bundled", entry["template_id"])
    workspace = list_workspace_template_summaries(root)
    for entry in workspace:
        entry["archived"] = is_archived(archived, "workspace", entry["slug"])
    return {"bundled": bundled, "workspace": workspace}


@router.post("/role-templates/archive")
def api_archive_profile(
    workspace_slug: str,
    body: ArchiveProfileBody,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    set_archived(
        Path(session.paths_root),
        source=body.source,  # type: ignore[arg-type]
        identifier=body.id,
        archived=body.archived,
    )
    return {"source": body.source, "id": body.id, "archived": body.archived}


@router.post("/role-templates/assist")
def api_find_candidate(
    workspace_slug: str,
    body: CandidateFinderBody,
    request: Request,
) -> dict:
    from pidgin.hr_assist.finder import find_candidates

    session = require_workspace_session(request, workspace_slug)
    candidates = list_bundled_template_summaries()
    reply, recommended = find_candidates(
        session.conn,
        message=body.message,
        history=[h.model_dump() for h in body.history],
        candidates=candidates,
    )
    return {"reply": reply, "recommended": recommended}


@router.get("/role-templates/bundled/{recipe_id}")
def api_get_bundled_template(workspace_slug: str, recipe_id: str, request: Request) -> dict:
    session = require_workspace_session(request, workspace_slug)
    try:
        detail = bundled_template_detail(recipe_id)
    except UnknownRecipeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    archived = load_archived(Path(session.paths_root))
    detail["archived"] = is_archived(archived, "bundled", recipe_id)
    return detail


@router.post("/hire")
def api_hire(workspace_slug: str, request: Request, body: HireBody | None = None) -> dict[str, str]:
    session = require_workspace_session(request, workspace_slug)
    try:
        if body is None or (
            body.template_id is None
            and body.slug is None
            and body.display_name is None
            and body.customization is None
        ):
            return hire_support_agent(session.conn, paths_root=session.paths_root)

        if body.template_source not in {"bundled", "workspace"}:
            raise HireError("template_source must be bundled or workspace")

        customization = (
            HireCustomization.model_validate(body.customization.model_dump())
            if body.customization is not None
            else None
        )
        return hire_with_template(
            session.conn,
            paths_root=session.paths_root,
            request=TemplateHireRequest(
                template_source=body.template_source,  # type: ignore[arg-type]
                template_id=body.template_id,
                slug=body.slug,
                workspace_version=body.version,
                customization=customization,
                display_name=body.display_name or "",
                handle=body.handle,
                manager_principal_id=body.manager_principal_id,
            ),
        )
    except HireError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agents/{handle}")
def api_get_agent(workspace_slug: str, handle: str, request: Request) -> dict:
    session = require_workspace_session(request, workspace_slug)
    agent = get_agent_by_handle(session.conn, handle)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {
        "id": agent["id"],
        "display_name": agent["display_name"],
        "role_title": agent["role_title"],
        "handle": agent["handle"],
        "current_status": agent["current_status"],
        "created_at": agent["created_at"],
    }


@router.get("/agents/{handle}/conversation")
def api_get_agent_conversation(workspace_slug: str, handle: str, request: Request) -> dict:
    session = require_workspace_session(request, workspace_slug)
    agent = get_agent_by_handle(session.conn, handle)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent["current_status"] == "offboarded":
        raise HTTPException(status_code=404, detail="Agent is archived")
    try:
        return ensure_agent_conversation(session.conn, handle)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agents/{handle}/messages")
def api_agent_messages(workspace_slug: str, handle: str, request: Request) -> dict:
    session = require_workspace_session(request, workspace_slug)
    agent = get_agent_by_handle(session.conn, handle)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    conversation_id = get_or_create_agent_conversation(session.conn, agent["id"])
    return {
        "conversation_id": conversation_id,
        "messages": list_messages(session.conn, conversation_id),
    }


@router.post("/agents/{handle}/messages")
def api_send_agent_message(
    workspace_slug: str,
    handle: str,
    body: SendMessageBody,
    request: Request,
    stream: bool = Query(False),
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    agent = get_agent_by_handle(session.conn, handle)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    log.info(
        "[chat] send message — handle=%s stream=%s body_len=%d",
        handle, stream, len(body.body),
    )
    try:
        message_id, event_id, conversation_id = send_chat_message(
            session.conn,
            agent_handle=handle,
            body_text=body.body,
            run_turn=not stream,
        )
    except ValueError as exc:
        log.error("[chat] send_chat_message failed — handle=%s error=%s", handle, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log.info(
        "[chat] message queued — message_id=%s event_id=%s conversation_id=%s",
        message_id, event_id, conversation_id,
    )
    if stream:
        return {
            "message_id": message_id,
            "event_id": event_id,
            "conversation_id": conversation_id,
            "stream_url": f"/{workspace_slug}/api/turns/stream/{event_id}",
        }
    return {
        "message_id": message_id,
        "event_id": event_id,
        "conversation_id": conversation_id,
        "messages": list_messages(session.conn, conversation_id),
    }


@router.post("/agents/{handle}/archive")
def api_archive_agent(workspace_slug: str, handle: str, request: Request) -> dict:
    session = require_workspace_session(request, workspace_slug)
    try:
        return archive_agent(
            session.conn,
            handle=handle,
            actor_principal_id=get_or_create_operator_principal(session.conn),
        )
    except ArchiveError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status, detail=detail) from exc


@router.get("/agents/{handle}/brief")
def api_get_agent_brief(workspace_slug: str, handle: str, request: Request) -> dict:
    session = require_workspace_session(request, workspace_slug)
    agent = get_agent_by_handle(session.conn, handle)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    customization = HireCustomization.from_json(agent.get("hire_customization_json"))
    return {
        "id": agent["id"],
        "handle": handle,
        "display_name": agent["display_name"],
        "role_title": agent["role_title"],
        "current_status": agent["current_status"],
        "created_at": agent["created_at"],
        "customization": customization.model_dump() if customization else None,
    }


@router.patch("/agents/{handle}/brief")
def api_patch_agent_brief(
    workspace_slug: str,
    handle: str,
    body: HireCustomizationBody,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    try:
        customization = HireCustomization.model_validate(body.model_dump())
        return update_agent_brief(
            session.conn,
            Path(session.paths_root),
            handle=handle,
            customization=customization,
            actor_principal_id=get_or_create_operator_principal(session.conn),
        )
    except BriefError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/common-instructions")
def api_get_common_instructions(workspace_slug: str, request: Request) -> dict:
    session = require_workspace_session(request, workspace_slug)
    return get_common_instructions(Path(session.paths_root))


@router.get("/common-instructions/default")
def api_get_default_common_instructions(workspace_slug: str, request: Request) -> dict:
    require_workspace_session(request, workspace_slug)
    return {"body_markdown": DEFAULT_COMMON_INSTRUCTIONS.strip()}


@router.put("/common-instructions")
def api_save_common_instructions(
    workspace_slug: str,
    body: CommonInstructionsBody,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    try:
        return save_common_instructions(
            Path(session.paths_root),
            body_markdown=body.body_markdown,
            actor_principal_id=get_or_create_operator_principal(session.conn),
        )
    except CommonInstructionsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agents/{handle}/effective-prompt")
def api_agent_effective_prompt(workspace_slug: str, handle: str, request: Request) -> dict:
    """The fully assembled system prompt for an agent — the *sum* of every
    instruction layer (common + role + per-agent brief) — so the admin
    configuring it can review the combined result and resolve any conflicts."""
    session = require_workspace_session(request, workspace_slug)
    agent_row = get_agent_by_handle(session.conn, handle)
    if agent_row is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    paths = WorkspacePaths(root=Path(session.paths_root))
    ctx = build_workspace_context_from_conn(
        workspace_id=session.workspace_id,
        paths=paths,
        conn=session.conn,
    )
    agent = ctx.turn_store.load_agent_context(agent_row["id"])
    common = get_common_instructions(paths.root)
    system_prompt = build_system_prompt(agent, common_instructions=common["body_markdown"])
    return {
        "handle": handle,
        "display_name": agent.display_name,
        "role_title": agent.role_title,
        "common_instructions_version": common["version"],
        "system_prompt": system_prompt,
    }


@router.post("/agents/{handle}/create-template")
def api_create_template_from_agent(
    workspace_slug: str,
    handle: str,
    body: CreateTemplateFromAgentBody,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    try:
        return create_template_from_agent(
            session.conn,
            Path(session.paths_root),
            handle=handle,
            name=body.name,
            slug=body.slug,
            actor_principal_id=get_or_create_operator_principal(session.conn),
        )
    except BriefError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/role-templates/workspace/{slug}")
def api_get_workspace_template(workspace_slug: str, slug: str, request: Request) -> dict:
    session = require_workspace_session(request, workspace_slug)
    try:
        return get_workspace_template(Path(session.paths_root), slug)
    except TemplateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/role-templates/workspace/{slug}/versions/{version}")
def api_get_workspace_template_version(
    workspace_slug: str,
    slug: str,
    version: int,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    try:
        return get_workspace_template(Path(session.paths_root), slug, version=version)
    except TemplateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/role-templates/workspace")
def api_create_workspace_template(
    workspace_slug: str,
    body: CreateWorkspaceTemplateBody,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    actor_id = get_or_create_operator_principal(session.conn)
    customization = (
        HireCustomization.model_validate(body.customization.model_dump())
        if body.customization is not None
        else None
    )
    try:
        if body.duplicate_from_recipe_id:
            return duplicate_bundled_template(
                Path(session.paths_root),
                name=body.name,
                slug=body.slug,
                recipe_id=body.duplicate_from_recipe_id,
                customization=customization,
                actor_principal_id=actor_id,
            )
        if customization is None:
            raise TemplateError("customization or duplicate_from_recipe_id is required")
        return create_workspace_template(
            Path(session.paths_root),
            name=body.name,
            slug=body.slug,
            customization=customization,
            actor_principal_id=actor_id,
        )
    except (TemplateError, BriefError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/role-templates/workspace/{slug}")
def api_patch_workspace_template(
    workspace_slug: str,
    slug: str,
    body: PatchWorkspaceTemplateBody,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    customization = HireCustomization.model_validate(body.customization.model_dump())
    try:
        return save_workspace_template_version(
            Path(session.paths_root),
            slug,
            name=body.name,
            customization=customization,
            actor_principal_id=get_or_create_operator_principal(session.conn),
        )
    except TemplateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/role-templates/workspace/{slug}")
def api_delete_workspace_template(workspace_slug: str, slug: str, request: Request) -> dict:
    session = require_workspace_session(request, workspace_slug)
    try:
        delete_workspace_template(Path(session.paths_root), slug)
    except TemplateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": slug}


@router.post("/hr-assist/sessions")
def api_create_hr_assist_session(
    workspace_slug: str,
    body: CreateHrAssistSessionBody,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    created = create_session(
        Path(session.paths_root),
        context_type=body.context_type,  # type: ignore[arg-type]
        context_id=body.context_id,
    )
    return {
        "session_id": created.session_id,
        "context_type": created.context_type,
        "context_id": created.context_id,
        "created_at": created.created_at,
        "updated_at": created.updated_at,
        "messages": [],
    }


@router.get("/hr-assist/sessions/{session_id}")
def api_get_hr_assist_session(
    workspace_slug: str,
    session_id: str,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    try:
        meta = get_session(Path(session.paths_root), session_id)
        messages = list_hr_assist_messages(Path(session.paths_root), session_id)
    except HrAssistError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "session_id": meta.session_id,
        "context_type": meta.context_type,
        "context_id": meta.context_id,
        "created_at": meta.created_at,
        "updated_at": meta.updated_at,
        "messages": messages,
    }


@router.get("/hr-assist/sessions/{session_id}/messages")
def api_list_hr_assist_messages(
    workspace_slug: str,
    session_id: str,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    try:
        messages = list_hr_assist_messages(Path(session.paths_root), session_id)
    except HrAssistError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"session_id": session_id, "messages": messages}


@router.post("/hr-assist/sessions/{session_id}/messages")
def api_send_hr_assist_message(
    workspace_slug: str,
    session_id: str,
    body: HrAssistMessageBody,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    draft = (
        HireCustomization.model_validate(body.customization.model_dump())
        if body.customization is not None
        else None
    )
    try:
        return send_operator_message(
            Path(session.paths_root),
            session_id,
            body_text=body.body_text,
            conn=session.conn,
            draft_customization=draft,
        )
    except HrAssistError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _dispatch_streaming_turn(workspace_id: str, paths_root: str, event_id: str) -> None:
    log.info("[stream] starting streaming turn — event_id=%s workspace=%s", event_id, workspace_id)
    paths = WorkspacePaths(root=Path(paths_root))
    conn = connect(paths.db_sqlite)
    try:
        # Atomically claim the event. The browser's EventSource auto-reconnects
        # when the server closes the stream, which re-hits this endpoint; without
        # this guard the same event would be dispatched (and answered) twice.
        claimed = conn.execute(
            "UPDATE inbound_events SET processing_status = ? "
            "WHERE id = ? AND processing_status = ?",
            (ProcessingStatus.DISPATCHING.value, event_id, ProcessingStatus.PENDING.value),
        )
        conn.commit()
        if claimed.rowcount == 0:
            log.warning(
                "[stream] event %s already claimed — skipping duplicate dispatch", event_id
            )
            return

        ctx = build_workspace_context_from_conn(
            workspace_id=workspace_id,
            paths=paths,
            conn=conn,
        )
        sink = KeyedTurnEventSink(turn_event_bus, event_id)
        dispatch_turn(ctx, event_id, event_sink=sink)
        log.info("[stream] streaming turn completed — event_id=%s", event_id)
    except Exception as exc:
        log.error(
            "[stream] streaming turn FAILED — event_id=%s error=%s",
            event_id,
            exc,
            exc_info=True,
        )
        # Emit the error over SSE so the UI can display it, then close stream
        error_sink = KeyedTurnEventSink(turn_event_bus, event_id)
        error_sink.emit(StreamEvent(type="error", error=str(exc)))
    finally:
        turn_event_bus.close(event_id)
        conn.close()
        log.debug("[stream] connection closed — event_id=%s", event_id)


@router.get("/turns/stream/{stream_key}")
async def api_turn_stream(workspace_slug: str, stream_key: str, request: Request):
    session = require_workspace_session(request, workspace_slug)
    loop = asyncio.get_running_loop()
    turn_event_bus.bind_loop(loop)
    queue = turn_event_bus.register(stream_key)
    dispatch_future = loop.run_in_executor(
        None,
        _dispatch_streaming_turn,
        session.workspace_id,
        session.paths_root,
        stream_key,
    )

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                if event is None:
                    yield format_sse(StreamEvent(type="invocation_end"))
                    break
                yield format_sse(event)
                if event.type == "invocation_end" and event.response is not None:
                    break
        finally:
            await dispatch_future

    return StreamingResponse(event_generator(), media_type="text/event-stream")


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


@router.get("/llm-invocations")
def api_list_llm_invocations(
    workspace_slug: str,
    request: Request,
    limit: int = 50,
    after: str | None = None,
) -> list[dict]:
    session = require_workspace_session(request, workspace_slug)
    return list_model_invocations(session.conn, limit=min(limit, 200), after=after)


@router.get("/integrations/catalog")
def api_integration_catalog(workspace_slug: str, request: Request) -> list[dict]:
    _ = workspace_slug
    require_workspace_session(request, workspace_slug)
    return get_integration_catalog()


@router.get("/integrations")
def api_list_integrations(workspace_slug: str, request: Request) -> list[dict]:
    session = require_workspace_session(request, workspace_slug)
    return list_integrations(session.conn)


@router.post("/integrations/{connector_type}/manual")
def api_connect_manual(
    workspace_slug: str,
    connector_type: str,
    body: ManualConnectBody,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    try:
        return connect_manual(
            session.conn,
            connector_type=connector_type,
            display_name=body.display_name,
            fields=body.fields,
        )
    except IntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/integrations/{connector_type}/oauth/start")
def api_oauth_start(
    workspace_slug: str,
    connector_type: str,
    request: Request,
    body: OAuthStartBody | None = None,
) -> dict:
    require_workspace_session(request, workspace_slug)
    redirect_base = str(request.base_url).rstrip("/")
    try:
        url, oauth_state = start_oauth(
            connector_type=connector_type,
            workspace_slug=workspace_slug,
            redirect_base=redirect_base,
        )
    except IntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.session[OAUTH_STATE_SESSION_KEY] = oauth_state
    if body and body.display_name:
        request.session["oauth_display_name"] = body.display_name
    return {"authorization_url": url}


@router.post("/integrations/{installation_id}/health")
def api_integration_health(
    workspace_slug: str,
    installation_id: str,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    try:
        return run_health_check(session.conn, installation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/integrations/{installation_id}/config")
def api_update_integration_config(
    workspace_slug: str,
    installation_id: str,
    body: IntegrationConfigBody,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    try:
        return update_integration_config(
            session.conn,
            installation_id=installation_id,
            updates=body.config,
        )
    except IntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/integrations/{installation_id}")
def api_disconnect_integration(
    workspace_slug: str,
    installation_id: str,
    request: Request,
) -> dict:
    session = require_workspace_session(request, workspace_slug)
    try:
        disconnect(session.conn, installation_id)
    except IntegrationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": installation_id}
