from __future__ import annotations

import json
import logging
from typing import Any

from pidgin.llm.types import ParsedAction
from pidgin.types import ActionType

log = logging.getLogger(__name__)

_VALID_ACTIONS = {action.value for action in ActionType}


def parse_tool_call(name: str, arguments: str | dict[str, Any]) -> ParsedAction | None:
    if name not in _VALID_ACTIONS:
        return None
    if isinstance(arguments, str):
        try:
            params = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            # Almost always means the stream was cut off mid-argument (e.g. hit
            # max_tokens) — the model didn't produce malformed JSON on purpose.
            # Surface this loudly since a silently-empty action here is exactly
            # what let the "say requires payload.text" crash go unexplained.
            log.warning(
                "[llm] tool call %r arguments failed to parse as JSON (len=%d) — "
                "likely truncated mid-generation; args preserved under 'raw': %r",
                name, len(arguments), arguments[:500],
            )
            params = {"raw": arguments}
    else:
        params = arguments
    if not isinstance(params, dict):
        params = {"value": params}
    return ParsedAction(action_type=ActionType(name), params=params)
