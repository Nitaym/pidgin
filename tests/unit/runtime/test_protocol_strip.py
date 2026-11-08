from __future__ import annotations

from pidgin.runtime.actions import _strip_protocol_blocks


def test_strips_trailing_suggestion_block_keeping_prose() -> None:
    """The exact shape HR emitted in chat: readable prose, then a raw
    pidgin-suggestion payload the wizard would parse but plain chat cannot."""
    text = (
        "Here's a draft mission for the hire.\n\n"
        "```pidgin-suggestion\n"
        '{"action": "apply", "targets": {"job_requirements.mission": "Serve customers."}}\n'
        "```"
    )
    cleaned = _strip_protocol_blocks(text)
    assert cleaned == "Here's a draft mission for the hire."
    assert "pidgin-suggestion" not in cleaned
    assert "{" not in cleaned


def test_strips_candidates_block() -> None:
    text = 'Take a look at Sam.\n```pidgin-candidates\n{"recommended": ["op"]}\n```'
    assert _strip_protocol_blocks(text) == "Take a look at Sam."


def test_leaves_ordinary_text_untouched() -> None:
    text = "Here is a normal reply with a `code span` and no protocol block."
    assert _strip_protocol_blocks(text) == text


def test_leaves_unrelated_code_fence_untouched() -> None:
    text = "Example:\n```json\n{\"ok\": true}\n```"
    assert _strip_protocol_blocks(text) == text


def test_block_only_message_falls_back_to_original() -> None:
    """A message that is nothing but a protocol block has no prose to salvage;
    keep the original rather than sending an empty message."""
    text = '```pidgin-suggestion\n{"action": "apply", "targets": {}}\n```'
    assert _strip_protocol_blocks(text) == text
