from __future__ import annotations

import json
import sqlite3

from pidgin.db.connection import SYSTEM_EMPLOYEE_ID
from pidgin.db.events import fetch_pending_events
from pidgin.recipes import RoleRecipe
from pidgin.recipes.permissions import parse_permission_overrides, resolve_permission_profile
from pidgin.storage.records import (
    AgentContextRecord,
    GateAuditRecord,
    InboundEventRecord,
    ModelInvocationRecord,
    TurnDetailRecord,
    TurnRecord,
)
from pidgin.types import ProcessingStatus, TrustLabel
from pidgin.types.customization import HireCustomization
from pidgin.util.ids import new_ulid, utc_now_iso


class SqliteTurnStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def fetch_pending_events(self, limit: int = 10) -> list[InboundEventRecord]:
        rows = fetch_pending_events(self._conn, limit=limit)
        return [_event_from_row(row) for row in rows]

    def get_event(self, event_id: str) -> InboundEventRecord | None:
        row = self._conn.execute(
            "SELECT * FROM inbound_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        return _event_from_row(row) if row else None

    def start_turn(self, event: InboundEventRecord) -> TurnRecord:
        turn_id = new_ulid()
        now = utc_now_iso()
        employee_id = event.target_ai_employee_id or SYSTEM_EMPLOYEE_ID
        self._conn.execute(
            """
            INSERT INTO turns (
              id, ai_employee_id, triggering_event_id, current_status, started_at
            ) VALUES (?, ?, ?, 'running', ?)
            """,
            (turn_id, employee_id, event.id, now),
        )
        self._conn.execute(
            """
            UPDATE inbound_events
            SET processing_status = ?, picked_up_at = ?, resulting_turn_id = ?
            WHERE id = ?
            """,
            (ProcessingStatus.DISPATCHING.value, now, turn_id, event.id),
        )
        self._conn.commit()
        return TurnRecord(
            id=turn_id,
            ai_employee_id=employee_id,
            triggering_event_id=event.id,
            current_status="running",
            started_at=now,
        )

    def update_turn_conversation(self, turn_id: str, conversation_id: str) -> None:
        self._conn.execute(
            "UPDATE turns SET conversation_id = ? WHERE id = ?",
            (conversation_id, turn_id),
        )
        self._conn.commit()

    def complete_turn(self, turn_id: str, event_id: str, status: str = "completed") -> None:
        now = utc_now_iso()
        self._conn.execute(
            "UPDATE turns SET current_status = ?, ended_at = ? WHERE id = ?",
            (status, now, turn_id),
        )
        self._conn.execute(
            """
            UPDATE inbound_events
            SET processing_status = ?, completed_at = ?
            WHERE id = ?
            """,
            (ProcessingStatus.DONE.value, now, event_id),
        )
        self._conn.commit()

    def load_agent_context(self, agent_id: str) -> AgentContextRecord:
        agent = self._conn.execute(
            "SELECT * FROM ai_employees WHERE id = ?",
            (agent_id,),
        ).fetchone()
        if agent is None:
            raise ValueError(f"Unknown agent: {agent_id}")

        snapshot = self._conn.execute(
            "SELECT bundle_json FROM ai_employee_recipe_snapshots WHERE id = ?",
            (agent["recipe_snapshot_id"],),
        ).fetchone()
        recipe = RoleRecipe.model_validate_json(snapshot["bundle_json"] if snapshot else "{}")
        overrides = parse_permission_overrides(agent["permission_overrides_json"])
        customization = HireCustomization.from_json(agent["hire_customization_json"])

        principal = self._conn.execute(
            "SELECT id FROM principals WHERE ai_employee_id = ? LIMIT 1",
            (agent_id,),
        ).fetchone()
        agent_principal_id = principal["id"] if principal else agent_id

        return AgentContextRecord(
            agent_id=agent_id,
            display_name=agent["display_name"],
            role_title=agent["role_title"],
            handle=agent["handle"],
            agent_principal_id=agent_principal_id,
            recipe=recipe,
            customization=customization,
            permission_profile=resolve_permission_profile(recipe, overrides),
            permission_overrides=overrides,
        )

    def count_invocations(self, turn_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM model_invocations WHERE turn_id = ?",
            (turn_id,),
        ).fetchone()
        return int(row["n"]) if row else 0

    def insert_invocation(self, record: ModelInvocationRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO model_invocations (
              id, turn_id, sequence_in_turn, provider, model_id,
              request_messages_json, request_tools_json, response_json,
              input_tokens, output_tokens, cost_usd_micros, latency_ms,
              error_text, invoked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.turn_id,
                record.sequence_in_turn,
                record.provider,
                record.model_id,
                record.request_messages_json,
                record.request_tools_json,
                record.response_json,
                record.input_tokens,
                record.output_tokens,
                record.cost_usd_micros,
                record.latency_ms,
                record.error_text,
                record.invoked_at,
            ),
        )
        self._conn.commit()

    def list_invocations(self, turn_id: str) -> list[ModelInvocationRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM model_invocations
            WHERE turn_id = ?
            ORDER BY sequence_in_turn ASC
            """,
            (turn_id,),
        ).fetchall()
        return [_invocation_from_row(row) for row in rows]

    def log_gate_decision(self, record: GateAuditRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO agent_action_log (
              id, turn_id, technical_actor, virtual_actor_ai_employee_id,
              virtual_actor_display_name, virtual_actor_role,
              requester_principal_id, requester_display_name,
              trust_label, policy_decision, action_type, action_params_json,
              outcome, model_invocation_id, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.turn_id,
                record.technical_actor,
                record.virtual_actor_ai_employee_id,
                record.virtual_actor_display_name,
                record.virtual_actor_role,
                record.requester_principal_id,
                record.requester_display_name,
                record.trust_label.value,
                record.policy_decision,
                record.action_type,
                record.action_params_json,
                record.outcome,
                record.model_invocation_id,
                record.occurred_at,
            ),
        )
        self._conn.commit()

    def list_gate_decisions(self, turn_id: str) -> list[GateAuditRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM agent_action_log
            WHERE turn_id = ?
            ORDER BY occurred_at ASC
            """,
            (turn_id,),
        ).fetchall()
        return [_gate_from_row(row) for row in rows]

    def get_turn_detail(self, turn_id: str) -> TurnDetailRecord | None:
        row = self._conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        if row is None:
            return None
        turn = _turn_from_row(row)
        event_row = self._conn.execute(
            "SELECT * FROM inbound_events WHERE id = ?",
            (turn.triggering_event_id,),
        ).fetchone()
        return TurnDetailRecord(
            turn=turn,
            triggering_event=_event_from_row(event_row) if event_row else None,
            invocations=self.list_invocations(turn_id),
            gate_decisions=self.list_gate_decisions(turn_id),
        )

    def list_turns(self, limit: int = 50) -> list[TurnRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM turns
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_turn_from_row(row) for row in rows]


def _event_from_row(row: sqlite3.Row) -> InboundEventRecord:
    payload = json.loads(row["payload_json"] or "{}")
    return InboundEventRecord(
        id=row["id"],
        trigger_type=row["trigger_type"],
        target_ai_employee_id=row["target_ai_employee_id"],
        sender_principal_id=row["sender_principal_id"],
        trust_label=TrustLabel(row["trust_label"]),
        payload=payload if isinstance(payload, dict) else {},
        processing_status=row["processing_status"],
    )


def _turn_from_row(row: sqlite3.Row) -> TurnRecord:
    return TurnRecord(
        id=row["id"],
        ai_employee_id=row["ai_employee_id"],
        conversation_id=row["conversation_id"],
        triggering_event_id=row["triggering_event_id"],
        current_status=row["current_status"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
    )


def _invocation_from_row(row: sqlite3.Row) -> ModelInvocationRecord:
    return ModelInvocationRecord(
        id=row["id"],
        turn_id=row["turn_id"],
        sequence_in_turn=row["sequence_in_turn"],
        provider=row["provider"],
        model_id=row["model_id"],
        request_messages_json=row["request_messages_json"],
        request_tools_json=row["request_tools_json"],
        response_json=row["response_json"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        cost_usd_micros=row["cost_usd_micros"],
        latency_ms=row["latency_ms"],
        error_text=row["error_text"],
        invoked_at=row["invoked_at"],
    )


def _gate_from_row(row: sqlite3.Row) -> GateAuditRecord:
    return GateAuditRecord(
        id=row["id"],
        turn_id=row["turn_id"],
        technical_actor=row["technical_actor"],
        virtual_actor_ai_employee_id=row["virtual_actor_ai_employee_id"],
        virtual_actor_display_name=row["virtual_actor_display_name"],
        virtual_actor_role=row["virtual_actor_role"],
        requester_principal_id=row["requester_principal_id"],
        requester_display_name=row["requester_display_name"],
        trust_label=TrustLabel(row["trust_label"]),
        policy_decision=row["policy_decision"],
        action_type=row["action_type"],
        action_params_json=row["action_params_json"],
        outcome=row["outcome"],
        model_invocation_id=row["model_invocation_id"],
        occurred_at=row["occurred_at"],
    )
