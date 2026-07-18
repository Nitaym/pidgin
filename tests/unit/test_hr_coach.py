from __future__ import annotations

from pidgin.hr_assist.coach import (
    _marketplace_instruction,
    _parse_reply,
    _validate_suggestion,
)
from pidgin.recipes.catalog import load_bundled_recipe
from pidgin.recipes.models import effective_customizable_fields

# The baseline field keys every recipe advertises (no recipe-declared extras).
_BASELINE = {f.key for f in effective_customizable_fields(None)}


def test_parse_reply_extracts_apply_suggestion() -> None:
    text = (
        "Here's a tighter mission you can use.\n"
        "```pidgin-suggestion\n"
        '{"action": "apply", "targets": {"job_requirements.mission": "Serve customers well."}}\n'
        "```"
    )
    body, suggestion = _parse_reply(text, _BASELINE)
    assert body == "Here's a tighter mission you can use."
    assert suggestion == {
        "action": "apply",
        "targets": {"job_requirements.mission": "Serve customers well."},
    }


def test_parse_reply_without_block_returns_plain_text() -> None:
    body, suggestion = _parse_reply("Tell me more about the role's scope.", _BASELINE)
    assert body == "Tell me more about the role's scope."
    assert suggestion is None


def test_parse_reply_ignores_malformed_json() -> None:
    text = "See note.\n```pidgin-suggestion\n{not json}\n```"
    body, suggestion = _parse_reply(text, _BASELINE)
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
    assert _validate_suggestion(raw, _BASELINE) == {
        "action": "apply",
        "targets": {"job_requirements.mission": "ok"},
    }


def test_validate_suggestion_append_requires_note() -> None:
    assert (
        _validate_suggestion({"action": "append_your_take", "targets": {}}, _BASELINE)
        is None
    )
    assert _validate_suggestion(
        {"action": "append_your_take", "targets": {"your_take": "Add examples."}},
        _BASELINE,
    ) == {"action": "append_your_take", "targets": {"your_take": "Add examples."}}


def test_validate_suggestion_rejects_unknown_action() -> None:
    assert (
        _validate_suggestion({"action": "delete_everything", "targets": {}}, _BASELINE)
        is None
    )
    assert _validate_suggestion("nonsense", _BASELINE) is None


def test_marketplace_instruction_lists_hireable_templates() -> None:
    """The coach is handed the bundled catalog so it can name real marketplace
    roles instead of guessing (the finder gets this; the coach used not to)."""
    text = _marketplace_instruction()
    assert text is not None
    # A representative bundled role appears by its display name.
    assert load_bundled_recipe("support-agent").display_name in text


def test_role_title_is_a_valid_target_when_recipe_declares_it() -> None:
    """A recipe that declares role_title customizable makes it a valid apply
    target (baseline alone rejects it)."""
    op = load_bundled_recipe("operating-partner")
    op_keys = {f.key for f in effective_customizable_fields(op)}
    raw = {"action": "apply", "targets": {"role_title": "Chief Strategy Officer"}}

    assert _validate_suggestion(raw, _BASELINE) is None
    assert _validate_suggestion(raw, op_keys) == {
        "action": "apply",
        "targets": {"role_title": "Chief Strategy Officer"},
    }
