from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pidgin.llm.types import LlmConfig, StreamEvent
from pidgin.storage.ports import ConversationStore, TurnStore
from pidgin.storage.records import AgentContextRecord, InboundEventRecord, TurnRecord
from pidgin.workspace.manager import WorkspacePaths


@dataclass(frozen=True)
class WorkspaceContext:
    workspace_id: str
    paths: WorkspacePaths
    turn_store: TurnStore
    conversation_store: ConversationStore
    llm_config: LlmConfig
    db_bridge: Any = field(default=None, repr=False, compare=False)


class EgressHandler(Protocol):
    def write(self, *, text: str, turn_id: str, extra: dict[str, Any] | None = None) -> None: ...


@dataclass(frozen=True)
class ActionContext:
    workspace: WorkspaceContext
    turn: TurnRecord
    event: InboundEventRecord
    agent: AgentContextRecord
    egress: EgressHandler
    invocation_id: str | None = None


class TurnEventSink(Protocol):
    def emit(self, event: StreamEvent) -> None: ...


class NullTurnEventSink:
    def emit(self, event: StreamEvent) -> None:
        _ = event
