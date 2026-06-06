from __future__ import annotations

from typing import Protocol

from pidgin.storage.records import (
    AgentContextRecord,
    ConversationMessageRecord,
    GateAuditRecord,
    InboundEventRecord,
    ModelInvocationRecord,
    TurnDetailRecord,
    TurnRecord,
)


class TurnStore(Protocol):
    def fetch_pending_events(self, limit: int = 10) -> list[InboundEventRecord]: ...

    def get_event(self, event_id: str) -> InboundEventRecord | None: ...

    def start_turn(self, event: InboundEventRecord) -> TurnRecord: ...

    def update_turn_conversation(self, turn_id: str, conversation_id: str) -> None: ...

    def complete_turn(self, turn_id: str, event_id: str, status: str = "completed") -> None: ...

    def load_agent_context(self, agent_id: str) -> AgentContextRecord: ...

    def count_invocations(self, turn_id: str) -> int: ...

    def insert_invocation(self, record: ModelInvocationRecord) -> None: ...

    def list_invocations(self, turn_id: str) -> list[ModelInvocationRecord]: ...

    def log_gate_decision(self, record: GateAuditRecord) -> None: ...

    def list_gate_decisions(self, turn_id: str) -> list[GateAuditRecord]: ...

    def get_turn_detail(self, turn_id: str) -> TurnDetailRecord | None: ...

    def list_turns(self, limit: int = 50) -> list[TurnRecord]: ...


class ConversationStore(Protocol):
    def list_messages(
        self, conversation_id: str, limit: int = 100
    ) -> list[ConversationMessageRecord]: ...

    def insert_message(
        self,
        *,
        conversation_id: str,
        sender_principal_id: str,
        sender_display_name: str,
        body_text: str,
        originating_turn_id: str | None = None,
    ) -> str: ...
