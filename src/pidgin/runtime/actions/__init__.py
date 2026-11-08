from __future__ import annotations

import json
import logging
import re
from typing import Any

from pidgin.gate.policy import gate
from pidgin.runtime.agent_load import load_agent_for_event
from pidgin.runtime.context import ActionContext, EgressHandler
from pidgin.types import GateRequest, ProposedAction
from pidgin.types.enums import ActionType
from pidgin.util.ids import new_ulid, utc_now_iso

log = logging.getLogger(__name__)

# Hard ceiling on connector read output fed back to the LLM (AGENT_RUNTIME_SPEC §5.3).
_READ_RESULT_CAP = 32 * 1024

# Wizard-only assist protocols (see hr_assist/coach.py and hr_assist/finder.py):
# the hire wizard parses these fenced blocks into an "Apply to form" button. In an
# ordinary conversation nothing parses them, so a stray block would dump raw JSON in
# front of the human. Strip it from anything we send outward as a safety net — the
# HR persona no longer instructs emitting them, but models still imitate the pattern.
_PROTOCOL_BLOCK = re.compile(r"```pidgin-(?:suggestion|candidates)\b.*?```", re.DOTALL)


def _strip_protocol_blocks(text: str) -> str:
    cleaned = _PROTOCOL_BLOCK.sub("", text)
    if cleaned == text:
        return text
    # Tidy the blank gap the removed block leaves behind; keep the original if
    # stripping would empty the message (a block-only send has nothing to salvage).
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned or text


def execute_action(action_ctx: ActionContext, action: ProposedAction) -> str:
    if action.action_type == ActionType.SAY:
        return _execute_say(action_ctx, action)
    if action.action_type == ActionType.POST:
        return _execute_post(action_ctx, action)
    if action.action_type == ActionType.READ:
        return _execute_read(action_ctx, action)
    if action.action_type == ActionType.EXECUTE:
        return _execute_execute(action_ctx, action)
    if action.action_type == ActionType.REMEMBER:
        return _execute_remember(action_ctx, action)
    if action.action_type == ActionType.RECALL:
        return _execute_recall(action_ctx, action)
    if action.action_type == ActionType.SCHEDULE_SELF:
        return _execute_schedule_self(action_ctx, action)
    if action.action_type == ActionType.OPEN_TASK:
        return _execute_open_task(action_ctx, action)
    if action.action_type == ActionType.CLOSE:
        return _execute_close(action_ctx, action)
    if action.action_type == ActionType.ESCALATE:
        return _execute_escalate(action_ctx, action)
    return f"Action {action.action_type.value} not implemented in MVP"


def _max_pending_timers(action_ctx: ActionContext) -> int:
    recipe = getattr(action_ctx.agent, "recipe", None)
    autonomy = getattr(recipe, "autonomy", None) if recipe is not None else None
    if autonomy and autonomy.limits and autonomy.limits.max_pending_timers:
        return autonomy.limits.max_pending_timers
    return 50


def _execute_say(action_ctx: ActionContext, action: ProposedAction) -> str:
    text = str(action.params.get("text") or "")
    if not text.strip():
        # Almost always a truncated LLM response (hit max_tokens mid tool-call)
        # rather than the agent deliberately choosing silence — see parse.py's
        # truncation warning and llm/providers/anthropic.py's max_tokens logging
        # for the upstream signal. Degrade to a soft error so the turn loop can
        # feed this back and let the model retry, instead of crashing the turn.
        log.warning(
            "[action] say called with empty/missing text — turn_id=%s params=%r",
            action_ctx.turn.id, action.params,
        )
        return "Missing text — say requires non-empty text; nothing was sent."
    text = _strip_protocol_blocks(text)
    action_ctx.egress.write(text=text, turn_id=action_ctx.turn.id)
    return f"Sent message ({len(text)} chars)"


def _execute_post(action_ctx: ActionContext, action: ProposedAction) -> str:
    """Target-driven outbound send — unlike say, the agent names the
    destination (URI / email / #channel) instead of replying in place."""
    target = str(action.params.get("target") or "")
    text = str(action.params.get("text") or "")
    if not target:
        return "Missing target"
    if not text:
        return "Missing text"
    text = _strip_protocol_blocks(text)
    conn = action_ctx.workspace.db_bridge
    if conn is None:
        return "Post requires connector bridge (not configured)"
    from pidgin.connectors.registry import resolve_resource
    from pidgin.connectors.targets import resolve_post_target
    from pidgin.connectors.types import PrincipalContext, WritePayload

    try:
        resource = resolve_post_target(conn, target)
        connector = resolve_resource(conn, resource)
        agent = action_ctx.agent
        attribution = f"{agent.display_name} · {agent.role_title} via Pidgin\n\n"
        result = connector.write(
            conn,
            resource,
            WritePayload(text=attribution + text),
            principal=PrincipalContext(
                principal_id=agent.agent_principal_id,
                display_name=agent.display_name,
                trust_label=action_ctx.event.trust_label,
            ),
            mode="execute",
        )
        return f"Posted to {resource} (ref={result.external_ref})"
    except Exception as exc:
        return f"Post failed: {exc}"


def _execute_read(action_ctx: ActionContext, action: ProposedAction) -> str:
    uri = str(action.params.get("resource_uri") or "")
    if not uri:
        return "Missing resource_uri"
    try:
        conn = action_ctx.workspace.db_bridge
        if conn is None:
            return "Read requires connector bridge (not configured)"
        from pidgin.connectors.registry import resolve_resource
        from pidgin.connectors.resources import parse_resource_uri
        from pidgin.connectors.types import PrincipalContext

        connector = resolve_resource(conn, uri)
        principal = PrincipalContext(
            principal_id=action_ctx.agent.agent_principal_id,
            display_name=action_ctx.agent.display_name,
            trust_label=action_ctx.event.trust_label,
        )
        resource = parse_resource_uri(uri)
        result = connector.read(conn, resource, principal=principal)
        # Connectors cap their own output, but enforce a hard ceiling here too
        # so a misbehaving connector can't blow up the next LLM invocation.
        text = result.text[:_READ_RESULT_CAP]
        if len(result.text) > _READ_RESULT_CAP:
            text += "\n\n[... truncated ...]"
        return f"Read {uri}:\n\n{text}" if text else f"Read {uri} (empty)"
    except Exception as exc:
        return f"Read failed: {exc}"


def _execute_execute(action_ctx: ActionContext, action: ProposedAction) -> str:
    """Create/update a connector resource (e.g. write a file to Drive).

    Only reached after the gate accepts the action as EXECUTED — external
    writes are staged for owner approval by policy before landing here.
    """
    uri = str(action.params.get("resource_uri") or "")
    if not uri:
        return "Missing resource_uri"
    conn = action_ctx.workspace.db_bridge
    if conn is None:
        return "Write requires connector bridge (not configured)"
    from pidgin.connectors.registry import resolve_resource
    from pidgin.connectors.resources import parse_resource_uri
    from pidgin.connectors.types import PrincipalContext, WritePayload

    try:
        resource = parse_resource_uri(uri)
        connector = resolve_resource(conn, resource)
        # Reaching here means the approval gate accepted this execute, so mark it
        # owner-approved — the signal a connector uses to allow a gated mutation
        # (e.g. editing an existing Drive file) vs. an ungated post/say.
        extra: dict[str, Any] = {
            "kind": str(action.params.get("kind") or "file"),
            "owner_approved": True,
        }
        op = str(action.params.get("op") or "").strip()
        if op:
            extra["op"] = op
            for key in ("range", "values", "value_input"):
                if action.params.get(key) is not None:
                    extra[key] = action.params.get(key)
        payload = WritePayload(
            text=str(action.params.get("content") or ""),
            subject=(str(action.params.get("name") or "").strip() or None),
            extra=extra,
        )
        result = connector.write(
            conn,
            resource,
            payload,
            principal=PrincipalContext(
                principal_id=action_ctx.agent.agent_principal_id,
                display_name=action_ctx.agent.display_name,
                trust_label=action_ctx.event.trust_label,
            ),
            mode="execute",
        )
        # Register what we just created under any active grant, so a later edit
        # or delete of it is recognised as the agent's own work (see gate_action).
        try:
            from pidgin.db.grants import record_grant_resource

            ext = result.external_ref or {}
            new_id = ext.get("id")
            if new_id:
                uri_kind = "folder" if ext.get("kind") == "folder" else "file"
                record_grant_resource(
                    conn,
                    ai_employee_id=action_ctx.agent.agent_id,
                    resource_uri=f"{resource.prefix}:{uri_kind}/{new_id}",
                )
        except Exception as exc:  # noqa: BLE001 — recording is best-effort
            log.warning("[execute] failed to record grant resource: %s", exc)
        return f"Wrote {resource} (ref={result.external_ref})"
    except Exception as exc:
        return f"Write failed: {exc}"


def _execute_schedule_self(action_ctx: ActionContext, action: ProposedAction) -> str:
    import json
    from datetime import UTC, datetime, timedelta

    from pidgin.db.timers import (
        count_pending_timers,
        create_timer,
        find_pending_timer_near,
        iso_utc,
        next_occurrence,
    )

    reason = str(action.params.get("reason") or "").strip()
    if not reason:
        return "Missing reason"
    conn = action_ctx.workspace.db_bridge
    if conn is None:
        return "schedule_self requires database bridge (not configured)"

    if count_pending_timers(conn, ai_employee_id=action_ctx.agent.agent_id) >= _max_pending_timers(action_ctx):
        return (
            "You already have the maximum number of pending wake-ups. Cancel or "
            "let some fire before scheduling more."
        )

    recurrence = action.params.get("recurrence")
    if recurrence:
        if not isinstance(recurrence, dict):
            return "recurrence must be an object (kind + schedule)"
        try:
            fire_at = next_occurrence(recurrence, after=datetime.now(tz=UTC))
        except ValueError as exc:
            return f"Invalid recurrence: {exc}"
        scheduled_at = iso_utc(fire_at)
        timer_id = create_timer(
            conn,
            ai_employee_id=action_ctx.agent.agent_id,
            scheduled_at=scheduled_at,
            reason=reason,
            originating_turn_id=action_ctx.turn.id,
            inherited_trust_label=action_ctx.event.trust_label.value,
            kind="recurring",
            recurrence_json=json.dumps(recurrence),
        )
        log.info(
            "[schedule_self] CREATED recurring timer=%s — turn_id=%s next=%s recurrence=%s reason=%r",
            timer_id, action_ctx.turn.id, scheduled_at, recurrence, reason[:60],
        )
        return (
            f"Recurring wake-up created (timer {timer_id}); next fire {scheduled_at}, "
            "then it re-arms automatically. Do not schedule this cadence again."
        )

    try:
        delay_minutes = float(action.params.get("delay_minutes") or 0)
    except (TypeError, ValueError):
        return "Invalid delay_minutes"
    if delay_minutes <= 0:
        return "Provide either delay_minutes (positive) or a recurrence"

    fire_at = datetime.now(tz=UTC) + timedelta(minutes=delay_minutes)
    scheduled_at = iso_utc(fire_at)
    existing = find_pending_timer_near(
        conn,
        ai_employee_id=action_ctx.agent.agent_id,
        originating_turn_id=action_ctx.turn.id,
        scheduled_at=scheduled_at,
    )
    if existing is not None:
        log.warning(
            "[schedule_self] DEDUPED duplicate — turn_id=%s delay_min=%s "
            "target=%s collides_with timer=%s@%s (this is the double-reminder guard firing)",
            action_ctx.turn.id, delay_minutes, scheduled_at,
            existing["id"], existing["scheduled_at"],
        )
        return (
            f"Already scheduled: a wake-up for this is set at "
            f"{existing['scheduled_at']} (timer {existing['id']}). "
            "Do not schedule it again."
        )
    timer_id = create_timer(
        conn,
        ai_employee_id=action_ctx.agent.agent_id,
        scheduled_at=scheduled_at,
        reason=reason,
        originating_turn_id=action_ctx.turn.id,
        inherited_trust_label=action_ctx.event.trust_label.value,
    )
    log.info(
        "[schedule_self] CREATED timer=%s — turn_id=%s delay_min=%s target=%s reason=%r",
        timer_id, action_ctx.turn.id, delay_minutes, scheduled_at, reason[:60],
    )
    return (
        f"Scheduled wake-up at {scheduled_at} (timer {timer_id}). "
        "Confirmed — do not call schedule_self again for this follow-up."
    )


def _execute_open_task(action_ctx: ActionContext, action: ProposedAction) -> str:
    from pidgin.db.tasks import create_task

    title = str(action.params.get("title") or "").strip()
    if not title:
        return "Missing task title"
    conn = action_ctx.workspace.db_bridge
    if conn is None:
        return "open_task requires database bridge (not configured)"
    task_id = create_task(
        conn,
        owner_principal_id=action_ctx.agent.agent_principal_id,
        title=title,
        description=str(action.params.get("description") or "") or None,
        due_at=str(action.params.get("due_at") or "") or None,
        source_turn_id=action_ctx.turn.id,
    )
    log.info("[open_task] CREATED task=%s — agent=%s title=%r", task_id, action_ctx.agent.handle, title[:60])
    return f"Opened task {task_id}: {title}"


def _execute_close(action_ctx: ActionContext, action: ProposedAction) -> str:
    from pidgin.db.tasks import set_task_status

    task_id = str(action.params.get("task_id") or "").strip()
    if not task_id:
        return "Missing task_id"
    status = str(action.params.get("status") or "done").strip()
    if status not in ("in_progress", "blocked", "done", "cancelled"):
        return "status must be one of: in_progress, blocked, done, cancelled"
    conn = action_ctx.workspace.db_bridge
    if conn is None:
        return "close requires database bridge (not configured)"
    ok = set_task_status(
        conn,
        task_id=task_id,
        owner_principal_id=action_ctx.agent.agent_principal_id,
        to_status=status,
        outcome=str(action.params.get("outcome") or "") or None,
    )
    if not ok:
        return f"No task {task_id} owned by you"
    return f"Task {task_id} → {status}"


def _execute_escalate(action_ctx: ActionContext, action: ProposedAction) -> str:
    """Hand work up to the human owner/manager via the agent's operator chat.

    Unlike say (replies in place) and post (names a destination), escalate always
    lands in the agent's primary operator conversation so the human sees it — even
    when the turn was self-anchored (a timer with no conversation).
    """
    from pidgin.db.chat import get_or_create_agent_conversation, insert_message

    text = str(action.params.get("text") or action.params.get("summary") or "").strip()
    if not text:
        return "Missing escalation text"
    conn = action_ctx.workspace.db_bridge
    if conn is None:
        return "escalate requires database bridge (not configured)"
    agent = action_ctx.agent
    conversation_id = get_or_create_agent_conversation(conn, agent.agent_id)
    insert_message(
        conn,
        conversation_id=conversation_id,
        sender_principal_id=agent.agent_principal_id,
        sender_display_name=agent.display_name,
        body_text=f"⬆️ Escalation from {agent.display_name} ({agent.role_title}):\n\n{text}",
        originating_turn_id=action_ctx.turn.id,
    )
    log.info("[escalate] agent=%s -> operator conversation=%s", agent.handle, conversation_id)
    return "Escalated to your operator (posted to your chat with them)."


def _execute_remember(action_ctx: ActionContext, action: ProposedAction) -> str:
    text = str(action.params.get("text") or "")
    if not text:
        return "Nothing to remember"
    from pidgin.knowledge.memory import remember

    remember(action_ctx.workspace.paths, handle=action_ctx.agent.handle, text=text)
    return "Remembered."


def _execute_recall(action_ctx: ActionContext, action: ProposedAction) -> str:
    query = str(action.params.get("query") or "")
    from pidgin.knowledge.memory import recall_grep, recall_tail

    tail = recall_tail(action_ctx.workspace.paths, handle=action_ctx.agent.handle, max_lines=20)
    if not query:
        return tail or "(empty journal)"
    matches = recall_grep(
        action_ctx.workspace.paths, handle=action_ctx.agent.handle, query=query
    )
    if not matches:
        return f"No matches for {query!r}. Recent journal:\n{tail}"
    return "\n".join(matches[:10])


def log_gate_decision(
    action_ctx: ActionContext,
    *,
    action: ProposedAction,
    gate_result,
    technical_actor: str,
) -> None:
    from pidgin.storage.records import GateAuditRecord

    requester_id = action_ctx.event.payload.get("sender_principal_id", "operator")
    requester_name = action_ctx.event.payload.get("sender_display_name", "You")
    record = GateAuditRecord(
        id=new_ulid(),
        turn_id=action_ctx.turn.id,
        technical_actor=technical_actor,
        virtual_actor_ai_employee_id=action_ctx.agent.agent_id,
        virtual_actor_display_name=action_ctx.agent.display_name,
        virtual_actor_role=action_ctx.agent.role_title,
        requester_principal_id=str(requester_id),
        requester_display_name=str(requester_name),
        trust_label=action_ctx.event.trust_label,
        policy_decision=gate_result.policy_decision.value,
        action_type=action.action_type.value,
        action_params_json=json.dumps(action.params),
        outcome=gate_result.outcome.value,
        model_invocation_id=action_ctx.invocation_id,
        occurred_at=utc_now_iso(),
    )
    action_ctx.workspace.turn_store.log_gate_decision(record)


def gate_action(action_ctx: ActionContext, action: ProposedAction):
    result = gate(
        GateRequest(
            trust_label=action_ctx.event.trust_label,
            action=action,
            permission_profile=action_ctx.agent.permission_profile,
            is_direct_commander=True,
        )
    )
    # Once the owner approves an agent's plan, an execution grant lets it keep
    # working that initiative without asking again: creates auto-approve, and so
    # do edits/deletes of resources it created this session. Anything it did NOT
    # create still stages (the pure gate's decision stands). See db/grants.py.
    from pidgin.types import GateOutcome

    if result.outcome == GateOutcome.STAGED and action.action_type == ActionType.EXECUTE:
        override = _grant_override(action_ctx, action)
        if override is not None:
            return override
    return result


def _grant_override(action_ctx: ActionContext, action: ProposedAction):
    conn = getattr(action_ctx.workspace, "db_bridge", None)
    if conn is None:
        return None
    from pidgin.db.grants import get_active_grant, is_granted_resource
    from pidgin.types import GateOutcome, GateResult, PolicyDecision

    agent_id = action_ctx.agent.agent_id
    if get_active_grant(conn, ai_employee_id=agent_id) is None:
        return None
    uri = str(action.params.get("resource_uri") or "")
    granted = GateResult(
        outcome=GateOutcome.EXECUTED, policy_decision=PolicyDecision.AUTO_APPROVED
    )
    # Creating inside a folder is additive → covered by the grant.
    if _is_create_target(uri):
        return granted
    # Editing/deleting an existing resource → only if we created it this session.
    if is_granted_resource(conn, ai_employee_id=agent_id, resource_uri=uri):
        return granted
    return None


def _is_create_target(uri: str) -> bool:
    """A folder-targeted execute creates new content inside it (additive)."""
    if not uri:
        return False
    try:
        from pidgin.connectors.resources import parse_resource_uri

        return getattr(parse_resource_uri(uri), "kind", None) == "folder"
    except Exception:  # noqa: BLE001 — unparseable URI is not a known-safe create
        return False


class PidginChatEgress:
    def __init__(
        self,
        *,
        workspace,
        conversation_id: str,
        agent_principal_id: str,
        agent_display_name: str,
        trust_label,
    ) -> None:
        self._workspace = workspace
        self._conversation_id = conversation_id
        self._agent_principal_id = agent_principal_id
        self._agent_display_name = agent_display_name
        self._trust_label = trust_label

    def write(self, *, text: str, turn_id: str, extra: dict[str, Any] | None = None) -> None:
        from pidgin.connectors.pidgin_chat.connector import PidginChatConnector
        from pidgin.connectors.pidgin_chat.ingress import conversation_resource_uri
        from pidgin.connectors.types import PrincipalContext, WritePayload

        # Bridge: connector still expects conn — use factory on workspace if available
        conn = self._workspace.db_bridge
        if conn is None:
            self._workspace.conversation_store.insert_message(
                conversation_id=self._conversation_id,
                sender_principal_id=self._agent_principal_id,
                sender_display_name=self._agent_display_name,
                body_text=text,
                originating_turn_id=turn_id,
            )
            return
        connector = PidginChatConnector()
        connector.write(
            conn,
            conversation_resource_uri(self._conversation_id),
            WritePayload(text=text, extra={"originating_turn_id": turn_id, **(extra or {})}),
            principal=PrincipalContext(
                principal_id=self._agent_principal_id,
                display_name=self._agent_display_name,
                trust_label=self._trust_label,
            ),
            mode="execute",
        )


class NullEgress:
    """No-op egress for admin inject events without a conversation."""

    def write(self, *, text: str, turn_id: str, extra: dict[str, Any] | None = None) -> None:
        _ = text, turn_id, extra


def build_egress(workspace, event) -> EgressHandler:
    payload = event.payload
    if payload.get("connector_type", "pidgin_chat") == "pidgin_chat":
        conversation_id = str(payload.get("conversation_id") or "")
        agent = load_agent_for_event(workspace, event)
        if not conversation_id:
            return NullEgress()
        return PidginChatEgress(
            workspace=workspace,
            conversation_id=conversation_id,
            agent_principal_id=agent.agent_principal_id,
            agent_display_name=agent.display_name,
            trust_label=event.trust_label,
        )
    if payload.get("connector_type") == "slack":
        return SlackEgress(workspace=workspace, event=event)
    raise ValueError(f"Unsupported connector type: {payload.get('connector_type')}")


class SlackEgress:
    def __init__(self, *, workspace, event) -> None:
        self._workspace = workspace
        self._event = event

    def write(self, *, text: str, turn_id: str, extra: dict[str, Any] | None = None) -> None:
        payload = self._event.payload
        installation_id = payload.get("connector_installation_id")
        if not installation_id:
            raise ValueError("Slack event missing connector_installation_id")
        conn = self._workspace.db_bridge
        if conn is None:
            raise ValueError("Slack egress requires database connection")
        from pidgin.connectors.registry import load_connector
        from pidgin.connectors.types import PrincipalContext, ResourceUri, WritePayload

        agent = load_agent_for_event(self._workspace, self._event)
        channel = str(payload.get("external_channel_id") or "")
        thread_ts = payload.get("external_thread_id")
        resource_id = f"{channel}:{thread_ts}" if thread_ts else channel
        connector = load_connector(conn, str(installation_id))
        attribution = f"{agent.display_name} · {agent.role_title} via Pidgin\n\n"
        slack_resource = ResourceUri(
            prefix="slack",
            kind="thread" if thread_ts else "channel",
            resource_id=resource_id,
        )
        connector.write(
            conn,
            slack_resource,
            WritePayload(text=attribution + text),
            principal=PrincipalContext(
                principal_id=agent.agent_principal_id,
                display_name=agent.display_name,
                trust_label=self._event.trust_label,
            ),
            mode="execute",
        )
