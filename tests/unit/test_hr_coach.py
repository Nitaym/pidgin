from __future__ import annotations

from pidgin.hr_assist.coach import _parse_reply, _validate_suggestion


def test_parse_reply_extracts_apply_suggestion() -> None:
    text = (
        "Here's a tighter mission you can use.\n"
        "```pidgin-suggestion\n"
        '{"action": "apply", "targets": {"job_requirements.mission": "Serve customers well."}}\n'
        "```"
    )
    body, suggestion = _parse_reply(text)
    assert body == "Here's a tighter mission you can use."
    assert suggestion == {
        "action": "apply",
        "targets": {"job_requirements.mission": "Serve customers well."},
    }


def test_parse_reply_without_block_returns_plain_text() -> None:
    body, suggestion = _parse_reply("Tell me more about the role's scope.")
    assert body == "Tell me more about the role's scope."
    assert suggestion is None


def test_parse_reply_ignores_malformed_json() -> None:
    text = "See note.\n```pidgin-suggestion\n{not json}\n```"
    body, suggestion = _parse_reply(text)
    assert suggestion is None
    assert "See note." in body


def test_validate_suggestion_drops_unknown_targets() -> None:
    raw = {
        "action": "apply",
        "targets": {
            "job_requirements.mission": "ok",
            "bogus.field": "nope",
            "ideal_candidate.tone": "  ",
        },
    }
    assert _validate_suggestion(raw) == {
        "action": "apply",
        "targets": {"job_requirements.mission": "ok"},
    }


def test_validate_suggestion_append_requires_note() -> None:
    assert _validate_suggestion({"action": "append_your_take", "targets": {}}) is None
    assert _validate_suggestion(
        {"action": "append_your_take", "targets": {"your_take": "Add examples."}}
    ) == {"action": "append_your_take", "targets": {"your_take": "Add examples."}}


def test_validate_suggestion_rejects_unknown_action() -> None:
    assert _validate_suggestion({"action": "delete_everything", "targets": {}}) is None
    assert _validate_suggestion("nonsense") is None
