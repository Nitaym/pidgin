from __future__ import annotations

from pidgin.llm.providers.stub import StubLLMProvider
from pidgin.llm.registry import register_provider
from pidgin.llm.types import LlmConfig
from pidgin.recipes import RoleRecipe
from pidgin.recipes.models import RecipePermissions
from pidgin.runtime.context import WorkspaceContext
from pidgin.runtime.turn_executor import TurnExecutor
from pidgin.storage.memory.turn_store import InMemoryTurnStore
from pidgin.storage.records import AgentContextRecord, InboundEventRecord
from pidgin.types import TriggerType, TrustLabel
from pidgin.types.customization import HireCustomization
from pidgin.workspace.manager import WorkspacePaths


class _CaptureEgress:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def write(self, *, text: str, turn_id: str, extra=None) -> None:
        _ = turn_id, extra
        self.messages.append(text)


def test_turn_executor_stub_say(tmp_path) -> None:
    register_provider("stub", StubLLMProvider())
    store = InMemoryTurnStore()
    recipe = RoleRecipe(
        recipe_id="support-agent",
        version="0.1.0",
        display_name="Support",
        role_title="Agent",
        permissions=RecipePermissions(
            can_read=["read", "recall"],
            can_write=["say"],
            requires_approval=[],
            blocked=[],
        ),
        system_prompt_template="You are {{display_name}}.",
    )
    store.seed_agent(
        AgentContextRecord(
            agent_id="agent-1",
            display_name="Support",
            role_title="Agent",
            handle="support",
            agent_principal_id="principal-1",
            recipe=recipe,
            customization=HireCustomization(),
            permission_profile=recipe.permissions.model_dump(),  # type: ignore[arg-type]
        )
    )
    # fix permission profile
    from pidgin.recipes.permissions import resolve_permission_profile

    agent = store.load_agent_context("agent-1")
    store.agents["agent-1"] = agent.model_copy(
        update={"permission_profile": resolve_permission_profile(recipe)}
    )

    event = InboundEventRecord(
        id="evt-1",
        trigger_type=TriggerType.DIRECT_ADDRESS.value,
        target_ai_employee_id="agent-1",
        sender_principal_id="op-1",
        trust_label=TrustLabel.INTERNAL_AUTHENTICATED,
        payload={"message_text": "hello", "connector_type": "pidgin_chat", "conversation_id": "c1"},
    )
    store.seed_event(event)
    paths = WorkspacePaths(root=tmp_path)
    ctx = WorkspaceContext(
        workspace_id="ws-1",
        paths=paths,
        turn_store=store,
        conversation_store=_FakeConversationStore(),
        llm_config=LlmConfig(default_backend="stub", default_model="stub"),
    )
    egress = _CaptureEgress()
    turn = TurnExecutor().run(ctx, event=event, egress=egress)
    assert turn.current_status == "completed"
    assert egress.messages
    assert store.count_invocations(turn.id) == 1


class _FakeConversationStore:
    def list_messages(self, conversation_id: str, limit: int = 100):
        _ = conversation_id, limit
        return []

    def insert_message(self, **kwargs: object) -> str:
        _ = kwargs
        return "msg-1"
