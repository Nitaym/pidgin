from __future__ import annotations

from copy import deepcopy

from pidgin.db.connection import SYSTEM_EMPLOYEE_ID
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
from pidgin.types import ProcessingStatus
from pidgin.types.customization import HireCustomization
from pidgin.util.ids import new_ulid, utc_now_iso


class InMemoryTurnStore:
    """Test double — no SQL."""

    def __init__(self) -> None:
        self.events: dict[str, InboundEventRecord] = {}
        self.turns: dict[str, TurnRecord] = {}
        self.invocations: list[ModelInvocationRecord] = []
        self.gate_decisions: list[GateAuditRecord] = []
        self.agents: dict[str, AgentContextRecord] = {}

    def seed_event(self, event: InboundEventRecord) -> None:
        self.events[event.id] = event

    def seed_agent(self, agent: AgentContextRecord) -> None:
        self.agents[agent.agent_id] = agent

    def fetch_pending_events(self, limit: int = 10) -> list[InboundEventRecord]:
        pending = [
            event
            for event in self.events.values()
            if event.processing_status == ProcessingStatus.PENDING.value
        ]
        pending.sort(key=lambda e: e.id)
        return pending[:limit]

    def get_event(self, event_id: str) -> InboundEventRecord | None:
        return self.events.get(event_id)

    def start_turn(self, event: InboundEventRecord) -> TurnRecord:
        turn_id = new_ulid()
        now = utc_now_iso()
        agent_id = event.target_ai_employee_id or SYSTEM_EMPLOYEE_ID
        turn = TurnRecord(
            id=turn_id,
            ai_employee_id=agent_id,
            triggering_event_id=event.id,
            current_status="running",
            started_at=now,
        )
        self.turns[turn_id] = turn
        updated = event.model_copy(update={"processing_status": ProcessingStatus.DISPATCHING.value})
        self.events[event.id] = updated
        return turn

    def update_turn_conversation(self, turn_id: str, conversation_id: str) -> None:
        turn = self.turns[turn_id]
        self.turns[turn_id] = turn.model_copy(update={"conversation_id": conversation_id})

    def complete_turn(self, turn_id: str, event_id: str, status: str = "completed") -> None:
        now = utc_now_iso()
        turn = self.turns[turn_id]
        self.turns[turn_id] = turn.model_copy(
            update={"current_status": status, "ended_at": now}
        )
        event = self.events[event_id]
        self.events[event_id] = event.model_copy(
            update={"processing_status": ProcessingStatus.DONE.value}
        )

    def load_agent_context(self, agent_id: str) -> AgentContextRecord:
        agent = self.agents.get(agent_id)
        if agent is None:
            raise ValueError(f"Unknown agent: {agent_id}")
        return deepcopy(agent)

    def count_invocations(self, turn_id: str) -> int:
        return sum(1 for row in self.invocations if row.turn_id == turn_id)

    def insert_invocation(self, record: ModelInvocationRecord) -> None:
        self.invocations.append(record)

    def list_invocations(self, turn_id: str) -> list[ModelInvocationRecord]:
        return [row for row in self.invocations if row.turn_id == turn_id]

    def log_gate_decision(self, record: GateAuditRecord) -> None:
        self.gate_decisions.append(record)

    def list_gate_decisions(self, turn_id: str) -> list[GateAuditRecord]:
        return [row for row in self.gate_decisions if row.turn_id == turn_id]

    def get_turn_detail(self, turn_id: str) -> TurnDetailRecord | None:
        turn = self.turns.get(turn_id)
        if turn is None:
            return None
        event = self.events.get(turn.triggering_event_id)
        return TurnDetailRecord(
            turn=turn,
            triggering_event=event,
            invocations=self.list_invocations(turn_id),
            gate_decisions=self.list_gate_decisions(turn_id),
        )

    def list_turns(self, limit: int = 50) -> list[TurnRecord]:
        turns = list(self.turns.values())
        turns.sort(key=lambda t: t.started_at, reverse=True)
        return turns[:limit]


def agent_context_from_row(agent: dict, snapshot_json: str) -> AgentContextRecord:
    recipe = RoleRecipe.model_validate_json(snapshot_json)
    overrides = parse_permission_overrides(agent.get("permission_overrides_json"))
    customization = HireCustomization.from_json(agent.get("hire_customization_json"))
    return AgentContextRecord(
        agent_id=agent["id"],
        display_name=agent["display_name"],
        role_title=agent["role_title"],
        handle=agent["handle"],
        agent_principal_id=agent.get("principal_id") or agent["id"],
        recipe=recipe,
        customization=customization,
        permission_profile=resolve_permission_profile(recipe, overrides),
        permission_overrides=overrides,
    )
