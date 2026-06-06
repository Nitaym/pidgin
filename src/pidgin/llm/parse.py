from __future__ import annotations

import json
from typing import Any

from pidgin.llm.types import ParsedAction
from pidgin.types import ActionType

_VALID_ACTIONS = {action.value for action in ActionType}


def parse_tool_call(name: str, arguments: str | dict[str, Any]) -> ParsedAction | None:
    if name not in _VALID_ACTIONS:
        return None
    if isinstance(arguments, str):
        try:
            params = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            params = {"raw": arguments}
    else:
        params = arguments
    if not isinstance(params, dict):
        params = {"value": params}
    return ParsedAction(action_type=ActionType(name), params=params)
