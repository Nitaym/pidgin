from __future__ import annotations

import json
import logging
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
from pidgin.storage.records import InboundEventRecord, ModelInvocationRecord, TurnRecord
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

        while sequence < max_invocations:
            sequence += 1
            log.info("[turn] LLM invocation #%d — turn_id=%s model=%s", sequence, turn.id, model_ref.model_id)

            request = ModelRequest(
                messages=messages,
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

            invocation_id = new_ulid()
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
            staged = False

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
                    log.info("[turn] action STAGED — turn_id=%s action=%s", turn.id, action.action_type.value)
                    staged = True
                    turn_status = "refused"
                    end_turn = True
                    break
                if gate_result.outcome == GateOutcome.REFUSED:
                    log.info("[turn] action REFUSED — turn_id=%s action=%s", turn.id, action.action_type.value)
                    tool_results.append(f"Refused: {gate_result.policy_decision.value}")
                    continue
                if gate_result.outcome == GateOutcome.EXECUTED:
                    log.debug("[turn] executing action — turn_id=%s action=%s", turn.id, action.action_type.value)
                    result = execute_action(action_ctx, action)
                    log.debug("[turn] action result — turn_id=%s result=%r", turn.id, result[:200] if result else result)
                    tool_results.append(result)
                    if action.action_type == ActionType.SAY:
                        end_turn = True

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
                        content="Tool results:\n" + "\n".join(tool_results),
                    )
                )

            if end_turn or staged:
                log.info("[turn] ending turn — turn_id=%s end_turn=%s staged=%s", turn.id, end_turn, staged)
                break

        ctx.turn_store.complete_turn(turn.id, event.id, status=turn_status)
        log.info("[turn] completed — turn_id=%s status=%s sequence=%d", turn.id, turn_status, sequence)

        if response is not None:
            sink.emit(
                StreamEvent(type="invocation_end", turn_id=turn.id, response=response)
            )
        detail = ctx.turn_store.get_turn_detail(turn.id)
        return detail.turn if detail is not None else turn


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


def _technical_actor(event: InboundEventRecord) -> str:
    connector = event.payload.get("connector_type", "pidgin_chat")
    if connector == "slack":
        installation = event.payload.get("connector_installation_id", "")
        return f"slack:{installation}"
    return "pidgin_chat"


def _logical_provider(backend: str) -> str:
    return "anthropic" if backend == "anthropic" else backend
