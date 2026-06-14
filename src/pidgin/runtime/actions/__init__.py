from __future__ import annotations

import json
import logging
from typing import Any

from pidgin.gate.policy import gate
from pidgin.runtime.agent_load import load_agent_for_event
from pidgin.runtime.context import ActionContext, EgressHandler
from pidgin.types import GateRequest, ProposedAction
from pidgin.types.enums import ActionType
from pidgin.util.ids import new_ulid, utc_now_iso

log = logging.getLogger(__name__)


def execute_action(action_ctx: ActionContext, action: ProposedAction) -> str:
    if action.action_type == ActionType.SAY:
        return _execute_say(action_ctx, action)
    if action.action_type == ActionType.POST:
        return _execute_post(action_ctx, action)
    if action.action_type == ActionType.READ:
        return _execute_read(action_ctx, action)
    if action.action_type == ActionType.REMEMBER:
        return _execute_remember(action_ctx, action)
    if action.action_type == ActionType.RECALL:
        return _execute_recall(action_ctx, action)
    if action.action_type == ActionType.SCHEDULE_SELF:
        return _execute_schedule_self(action_ctx, action)
    return f"Action {action.action_type.value} not implemented in MVP"


def _execute_say(action_ctx: ActionContext, action: ProposedAction) -> str:
    text = str(action.params.get("text") or "")
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
        from pidgin.connectors.types import PrincipalContext

        connector = resolve_resource(conn, uri)
        principal = PrincipalContext(
            principal_id=action_ctx.agent.agent_principal_id,
            display_name=action_ctx.agent.display_name,
            trust_label=action_ctx.event.trust_label,
        )
        # Connectors still use conn internally — resolved via workspace paths in future
        _ = connector, principal
        return f"Read not fully wired for {uri} (connector resolved)"
    except Exception as exc:
        return f"Read failed: {exc}"


def _execute_schedule_self(action_ctx: ActionContext, action: ProposedAction) -> str:
    from datetime import UTC, datetime, timedelta

    from pidgin.db.timers import create_timer, find_pending_timer_near

    try:
        delay_minutes = float(action.params.get("delay_minutes") or 0)
    except (TypeError, ValueError):
        return "Invalid delay_minutes"
    reason = str(action.params.get("reason") or "").strip()
    if delay_minutes <= 0:
        return "delay_minutes must be positive"
    if not reason:
        return "Missing reason"
    conn = action_ctx.workspace.db_bridge
    if conn is None:
        return "schedule_self requires database bridge (not configured)"

    fire_at = datetime.now(tz=UTC) + timedelta(minutes=delay_minutes)
    scheduled_at = fire_at.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
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
    return gate(
        GateRequest(
            trust_label=action_ctx.event.trust_label,
            action=action,
            permission_profile=action_ctx.agent.permission_profile,
            is_direct_commander=True,
        )
    )


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
