from __future__ import annotations

from pidgin.storage.memory.turn_store import InMemoryTurnStore
from pidgin.storage.records import InboundEventRecord, ModelInvocationRecord
from pidgin.types import TriggerType, TrustLabel
from pidgin.util.ids import utc_now_iso


def test_in_memory_turn_store_invocation_roundtrip() -> None:
    store = InMemoryTurnStore()
    event = InboundEventRecord(
        id="evt-1",
        trigger_type=TriggerType.DIRECT_ADDRESS.value,
        target_ai_employee_id="agent-1",
        sender_principal_id="op-1",
        trust_label=TrustLabel.INTERNAL_AUTHENTICATED,
        payload={"message_text": "hi"},
    )
    store.seed_event(event)
    turn = store.start_turn(event)
    store.insert_invocation(
        ModelInvocationRecord(
            id="inv-1",
            turn_id=turn.id,
            sequence_in_turn=1,
            provider="stub",
            model_id="stub",
            request_messages_json="[]",
            request_tools_json="[]",
            response_json="{}",
            invoked_at=utc_now_iso(),
        )
    )
    assert store.count_invocations(turn.id) == 1
    detail = store.get_turn_detail(turn.id)
    assert detail is not None
    assert len(detail.invocations) == 1
