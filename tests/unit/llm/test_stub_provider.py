from __future__ import annotations

from pidgin.llm.providers.stub import StubLLMProvider
from pidgin.llm.types import ChatMessage, ModelRef, ModelRequest


def test_stub_complete_returns_say_action() -> None:
    provider = StubLLMProvider()
    request = ModelRequest(
        messages=[ChatMessage(role="user", content="hello")],
        tools=[],
        model_ref=ModelRef(backend="stub", model_id="stub"),
    )
    response = provider.complete(request)
    assert response.actions
    assert response.actions[0].action_type.value == "say"
    reply_text = response.actions[0].params.get("text", "")
    assert "hello" in reply_text.lower() or reply_text


def test_stub_stream_yields_deltas_and_end() -> None:
    provider = StubLLMProvider()
    request = ModelRequest(
        messages=[ChatMessage(role="user", content="Need help")],
        tools=[],
        model_ref=ModelRef(backend="stub", model_id="stub"),
    )
    events = list(provider.stream(request))
    types = [event.type for event in events]
    assert "text_delta" in types
    assert "invocation_end" in types
