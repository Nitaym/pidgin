from __future__ import annotations

import json
import logging
import os
import time

from pidgin.llm.config import effective_model_ref
from pidgin.llm.providers.base import LLMProvider
from pidgin.llm.registry import get_provider
from pidgin.llm.tools import tools_for_profile
from pidgin.llm.types import (
    ChatMessage,
    ModelRequest,
    ModelResponse,
    StreamEvent,
)
from pidgin.runtime.actions import (
    ActionContext,
    EgressHandler,
    execute_action,
    gate_action,
    log_gate_decision,
)
from pidgin.runtime.agent_load import load_agent_for_event
from pidgin.runtime.context import NullTurnEventSink, TurnEventSink, WorkspaceContext
from pidgin.runtime.prompt import assemble_messages
from pidgin.storage.records import (
    AgentContextRecord,
    InboundEventRecord,
    ModelInvocationRecord,
    TurnRecord,
)
from pidgin.types import ActionType, GateOutcome, ProposedAction
from pidgin.util.ids import new_ulid, utc_now_iso

log = logging.getLogger(__name__)


class TurnExecutor:
    def run(
        self,
        ctx: WorkspaceContext,
        *,
        event: InboundEventRecord,
        egress: EgressHandler,
        event_sink: TurnEventSink | None = None,
    ) -> TurnRecord:
        sink = event_sink or NullTurnEventSink()

        log.info(
            "[turn] starting — event_id=%s type=%s",
            event.id,
            event.trigger_type,
        )

        try:
            agent = load_agent_for_event(ctx, event)
        except Exception as exc:
            log.error("[turn] failed to load agent — event_id=%s error=%s", event.id, exc, exc_info=True)
            raise

        log.info(
            "[turn] agent loaded — handle=%s display_name=%s",
            agent.handle,
            agent.display_name,
        )

        turn = ctx.turn_store.start_turn(event)
        log.debug("[turn] turn record created — turn_id=%s", turn.id)

        conversation_id = event.payload.get("conversation_id")
        if conversation_id:
            ctx.turn_store.update_turn_conversation(turn.id, str(conversation_id))
            log.debug("[turn] conversation_id=%s attached to turn_id=%s", conversation_id, turn.id)

        try:
            messages = assemble_messages(ctx, agent=agent, event=event)
        except Exception as exc:
            log.error("[turn] failed to assemble messages — turn_id=%s error=%s", turn.id, exc, exc_info=True)
            raise

        log.info(
            "[turn] messages assembled — turn_id=%s count=%d (system + %d history + user)",
            turn.id,
            len(messages),
            len(messages) - 2,  # subtract system + user
        )
        log.debug("[turn] message roles: %s", [m.role for m in messages])

        tool_specs = tools_for_profile(agent.permission_profile)
        model_ref = effective_model_ref(ctx.llm_config)
        log.info(
            "[turn] LLM config — model=%s backend=%s tools=%d",
            model_ref.model_id,
            model_ref.backend,
            len(tool_specs),
        )

        try:
            provider = get_provider(model_ref.backend)
        except Exception as exc:
            log.error("[turn] failed to get LLM provider — backend=%s error=%s", model_ref.backend, exc, exc_info=True)
            raise

        technical_actor = _technical_actor(event)
        max_invocations = ctx.llm_config.budgets.max_invocations_per_turn
        sequence = 0
        turn_status = "completed"
        response = None
        # Actions that need owner approval accumulate here across the whole turn
        # and are bundled into ONE approval at the end, rather than each one
        # ending the turn on the spot. This is what lets the agent lay out a
        # full plan (folder + doc + …) that the owner signs off once.
        staged_actions: list[ProposedAction] = []

        while sequence < max_invocations:
            sequence += 1
            invocation_id = new_ulid()
            short_ref = f"req-{invocation_id[-6:].lower()}"
            log.info(
                "[turn] LLM invocation #%d — turn_id=%s model=%s ref=%s",
                sequence, turn.id, model_ref.model_id, short_ref,
            )

            request = ModelRequest(
                messages=_stamp_debug_ref(messages, short_ref),
                tools=tool_specs,
                model_ref=model_ref,
            )
            started = time.perf_counter()
            try:
                response = _invoke(provider, request, sink, turn_id=turn.id, sequence=sequence)
            except Exception as exc:
                log.error(
                    "[turn] LLM invocation #%d CRASHED — turn_id=%s error=%s",
                    sequence, turn.id, exc, exc_info=True,
                )
                turn_status = "failed"
                sink.emit(StreamEvent(type="error", turn_id=turn.id, error=str(exc)))
                break

            latency_ms = int((time.perf_counter() - started) * 1000)
            log.info(
                "[turn] LLM invocation #%d done — turn_id=%s latency_ms=%d stop_reason=%s "
                "input_tokens=%s output_tokens=%s error_text=%s",
                sequence,
                turn.id,
                latency_ms,
                response.stop_reason,
                response.usage.input_tokens if response.usage else "?",
                response.usage.output_tokens if response.usage else "?",
                response.error_text or "none",
            )

            ctx.turn_store.insert_invocation(
                ModelInvocationRecord(
                    id=invocation_id,
                    turn_id=turn.id,
                    sequence_in_turn=sequence,
                    provider=_logical_provider(model_ref.backend),
                    model_id=model_ref.model_id,
                    request_messages_json=json.dumps(
                        [m.model_dump() for m in request.messages]
                    ),
                    request_tools_json=json.dumps([t.model_dump() for t in tool_specs]),
                    response_json=json.dumps(response.model_dump()),
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cost_usd_micros=provider.estimate_cost_usd_micros(
                        model_ref.model_id, response.usage
                    ),
                    latency_ms=latency_ms,
                    error_text=response.error_text,
                    invoked_at=utc_now_iso(),
                )
            )

            if response.stop_reason == "error":
                log.error(
                    "[turn] LLM returned error stop — turn_id=%s error_text=%s",
                    turn.id,
                    response.error_text,
                )
                error_msg = response.error_text or "LLM returned an error"
                sink.emit(StreamEvent(type="error", turn_id=turn.id, error=error_msg))
                turn_status = "failed"
                break

            if response.stop_reason == "max_tokens":
                log.warning(
                    "[turn] LLM invocation #%d TRUNCATED by max_tokens — turn_id=%s "
                    "output_tokens=%s assistant_text_len=%d actions_parsed=%s "
                    "(cut off mid-generation; downstream action params may be incomplete)",
                    sequence, turn.id,
                    response.usage.output_tokens if response.usage else "?",
                    len(response.assistant_text or ""),
                    [a.action_type.value for a in response.actions],
                )

            action_ctx = ActionContext(
                workspace=ctx,
                turn=turn,
                event=event,
                agent=agent,
                egress=egress,
                invocation_id=invocation_id,
            )

            actions = [
                ProposedAction(action_type=p.action_type, params=p.params)
                for p in response.actions
            ]
            if not actions and response.assistant_text:
                actions = [
                    ProposedAction(
                        action_type=ActionType.SAY,
                        params={"text": response.assistant_text},
                    )
                ]

            log.info(
                "[turn] actions proposed — turn_id=%s count=%d types=%s",
                turn.id,
                len(actions),
                [a.action_type.value for a in actions],
            )

            tool_results: list[str] = []
            end_turn = response.stop_reason == "end_turn"

            for action in actions:
                gate_result = gate_action(action_ctx, action)
                log.debug(
                    "[turn] gate — action=%s outcome=%s",
                    action.action_type.value,
                    gate_result.outcome.value,
                )
                log_gate_decision(
                    action_ctx,
                    action=action,
                    gate_result=gate_result,
                    technical_actor=technical_actor,
                )

                if gate_result.outcome == GateOutcome.STAGED:
                    # Don't abandon the turn on the first action needing approval —
                    # queue it and let the agent keep planning the rest of its work.
                    # Everything queued this turn is bundled into one approval below.
                    log.info(
                        "[turn] action STAGED (queued into plan) — turn_id=%s action=%s",
                        turn.id, action.action_type.value,
                    )
                    staged_actions.append(action)
                    tool_results.append(
                        _label_tool_result(
                            action.action_type.value,
                            "Queued for the owner's approval as part of this turn's plan. "
                            "It will run automatically once the owner approves — you do NOT "
                            "need to ask again. Continue with any remaining steps, then end "
                            "with a short say summarizing what you've queued.",
                        )
                    )
                    continue
                if gate_result.outcome == GateOutcome.REFUSED:
                    log.info("[turn] action REFUSED — turn_id=%s action=%s", turn.id, action.action_type.value)
                    tool_results.append(
                        _label_tool_result(
                            action.action_type.value,
                            f"Refused: {gate_result.policy_decision.value}",
                        )
                    )
                    continue
                if gate_result.outcome == GateOutcome.EXECUTED:
                    log.debug("[turn] executing action — turn_id=%s action=%s", turn.id, action.action_type.value)
                    try:
                        result = execute_action(action_ctx, action)
                    except Exception as exc:
                        # Safety net: no single action handler should be able to take down
                        # the whole turn (the 2026-07-03 "say requires payload.text" crash
                        # happened because _execute_say had no such guard). Log loudly and
                        # feed the failure back as a tool result instead of propagating.
                        log.error(
                            "[turn] action EXECUTION CRASHED — turn_id=%s action=%s params=%r "
                            "error=%s",
                            turn.id, action.action_type.value, action.params, exc, exc_info=True,
                        )
                        result = f"Action failed: {exc}"
                    log.debug("[turn] action result — turn_id=%s result=%r", turn.id, result[:200] if result else result)
                    tool_results.append(_label_tool_result(action.action_type.value, result))
                    if action.action_type == ActionType.SAY:
                        if str(action.params.get("text") or "").strip():
                            end_turn = True
                        else:
                            log.warning(
                                "[turn] SAY had no text — turn_id=%s; continuing turn instead of "
                                "ending it silently, so the model gets a chance to retry",
                                turn.id,
                            )

            if tool_results and not end_turn:
                log.debug("[turn] appending tool results for next invocation — turn_id=%s count=%d", turn.id, len(tool_results))
                messages.append(
                    ChatMessage(
                        role="assistant",
                        content=response.assistant_text or json.dumps(response.model_dump()),
                    )
                )
                messages.append(
                    ChatMessage(
                        role="user",
                        content="Tool results:\n\n" + "\n\n".join(tool_results),
                    )
                )

            if end_turn:
                log.info("[turn] ending turn — turn_id=%s end_turn=%s", turn.id, end_turn)
                break
        else:
            # Loop ran out of invocations without ever hitting a `break` above —
            # no successful say, no staged action, no error. The agent silently
            # never replied this turn (e.g. repeated truncation churning through
            # the whole budget). Surface this clearly instead of a quiet "completed".
            log.warning(
                "[turn] invocation BUDGET EXHAUSTED without ending turn — turn_id=%s "
                "max_invocations=%d (agent never produced a completed reply this turn)",
                turn.id, max_invocations,
            )
            turn_status = "incomplete"

        if staged_actions:
            # The turn produced a plan that needs sign-off: persist all queued
            # actions as ONE approval and suspend the turn. approve_pending_approval
            # runs them and re-dispatches a continuation turn so the agent picks up
            # where it left off.
            turn_status = "suspended"
            approval_id = _stage_plan_for_approval(
                ctx, turn=turn, event=event, agent=agent, actions=staged_actions, egress=egress,
            )
            if approval_id:
                log.info(
                    "[turn] plan persisted as pending_approval=%s (%d action[s]) — turn_id=%s",
                    approval_id, len(staged_actions), turn.id,
                )

        ctx.turn_store.complete_turn(turn.id, event.id, status=turn_status)
        log.info("[turn] completed — turn_id=%s status=%s sequence=%d", turn.id, turn_status, sequence)

        if response is not None:
            sink.emit(
                StreamEvent(type="invocation_end", turn_id=turn.id, response=response)
            )
        detail = ctx.turn_store.get_turn_detail(turn.id)
        return detail.turn if detail is not None else turn


def _stage_plan_for_approval(
    ctx: WorkspaceContext,
    *,
    turn: TurnRecord,
    event: InboundEventRecord,
    agent: AgentContextRecord,
    actions: list[ProposedAction],
    egress: EgressHandler,
) -> str | None:
    """Persist a turn's queued actions as ONE pending_approval and notify the owner.

    All actions the gate STAGED this turn are bundled into a single "plan"
    approval, so the owner signs off once instead of once per file. On approval,
    services/approvals runs every action in order and re-dispatches the agent so
    it continues from where it left off (see the 2026-07 "Agent Enablement stops
    on every approval" investigation).
    """
    conn = ctx.db_bridge
    if conn is None:
        log.warning(
            "[turn] cannot persist pending approval (no db_bridge) — turn_id=%s actions=%d",
            turn.id, len(actions),
        )
        return None

    from pidgin.db.approvals import create_pending_approval
    from pidgin.db.principals import get_or_create_operator_principal

    requester_id = str(event.payload.get("sender_principal_id") or "operator")
    approver_id = get_or_create_operator_principal(conn)
    plan_params = {
        "actions": [
            {"action_type": a.action_type.value, "params": a.params} for a in actions
        ]
    }
    approval_id = create_pending_approval(
        conn,
        ai_employee_id=agent.agent_id,
        originating_turn_id=turn.id,
        proposed_action="plan",
        proposed_action_params=plan_params,
        trust_label=event.trust_label.value,
        requesting_principal_id=requester_id,
        requires_approver_principal_id=approver_id,
    )

    steps = "\n".join(
        f"  {i}. {_describe_staged_action(a)}" for i, a in enumerate(actions, 1)
    )
    plural = "step" if len(actions) == 1 else "steps"
    notice = (
        f"⏸️ I've prepared {len(actions)} {plural} that need your approval before I "
        f"continue:\n{steps}\n\n"
        f"Approve the plan (ref ...{approval_id[-6:]}) and I'll run all of it and pick "
        f"up where I left off."
    )
    try:
        # pending_approval_id rides along in the message's attachments so the
        # chat UI can render Approve/Reject right here, not only on the
        # separate Approvals page.
        egress.write(text=notice, turn_id=turn.id, extra={"pending_approval_id": approval_id})
    except Exception as exc:
        log.warning(
            "[turn] failed to post approval notice — turn_id=%s approval_id=%s error=%s",
            turn.id, approval_id, exc,
        )
    return approval_id


def _describe_staged_action(action: ProposedAction) -> str:
    if action.action_type == ActionType.EXECUTE:
        kind = action.params.get("kind") or "file"
        name = action.params.get("name") or "(unnamed)"
        target = action.params.get("resource_uri") or "?"
        return f'create {kind} "{name}" in {target}'
    return f"{action.action_type.value} ({json.dumps(action.params)[:200]})"


def _invoke(
    provider: LLMProvider,
    request: ModelRequest,
    sink: TurnEventSink,
    *,
    turn_id: str,
    sequence: int,
) -> ModelResponse:
    if isinstance(sink, NullTurnEventSink):
        log.debug("[invoke] non-streaming LLM call — turn_id=%s seq=%d", turn_id, sequence)
        return provider.complete(request)

    log.debug("[invoke] streaming LLM call — turn_id=%s seq=%d", turn_id, sequence)
    final: ModelResponse | None = None
    for event in provider.stream(request):
        enriched = event.model_copy(update={"turn_id": turn_id, "sequence": sequence})
        if enriched.type == "error":
            log.error("[invoke] LLM stream error — turn_id=%s error=%s", turn_id, enriched.error)
        elif enriched.type == "text_delta":
            log.debug("[invoke] text_delta — turn_id=%s len=%d", turn_id, len(enriched.delta or ""))
        if enriched.type in ("text_delta", "tool_call_ready", "usage", "error"):
            sink.emit(enriched)
        if enriched.type == "invocation_end" and enriched.response is not None:
            log.debug("[invoke] invocation_end received from provider — turn_id=%s", turn_id)
            final = enriched.response
    if final is None:
        log.warning("[invoke] no invocation_end from stream, falling back to complete() — turn_id=%s", turn_id)
        return provider.complete(request)
    return final


def _label_tool_result(tool_name: str, result: str) -> str:
    """Tag a tool's output with the tool that produced it.

    Without this the runtime joins every tool output into one unlabeled blob, so
    a model that called several tools in one response can't tell which result
    belongs to which call. The label also makes the result legible in the LLM
    inspector.
    """
    return f"## {tool_name} result:\n{result}"


def _stamp_debug_ref(messages: list[ChatMessage], short_ref: str) -> list[ChatMessage]:
    """Tag the request with a short ref and ask the model to echo it.

    The ref is the tail of the invocation record id, so a "[req-xxxxxx]" prefix
    arriving in Slack/chat points at the exact model_invocations row that
    produced it — duplicate refs mean one response was delivered twice,
    distinct refs for the same reply mean the turn itself ran twice.
    Disable with PIDGIN_LLM_DEBUG_REF=0 once done debugging.
    """
    if os.getenv("PIDGIN_LLM_DEBUG_REF", "1").lower() in {"0", "false", "no"}:
        return list(messages)
    if not messages or messages[0].role != "system":
        return list(messages)
    head = messages[0]
    stamped = head.model_copy(
        update={
            "content": (
                f"{head.content}\n\n---\n"
                f"**Debug request ref:** {short_ref}\n"
                f'Start the text of every reply you produce in this response '
                f'(including the text param of say/post actions) with "[{short_ref}] ".'
            )
        }
    )
    return [stamped, *messages[1:]]


def _technical_actor(event: InboundEventRecord) -> str:
    connector = event.payload.get("connector_type", "pidgin_chat")
    if connector == "slack":
        installation = event.payload.get("connector_installation_id", "")
        return f"slack:{installation}"
    return "pidgin_chat"


def _logical_provider(backend: str) -> str:
    return "anthropic" if backend == "anthropic" else backend
