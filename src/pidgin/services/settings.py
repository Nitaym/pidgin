"""Workspace-level settings — currently just the LLM model choice.

Stored in the `workspace.settings_json` blob under the `llm` key, the same
shape `pidgin.llm.config.load_llm_config` reads at turn-dispatch time.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from pidgin.util.ids import utc_now_iso

AVAILABLE_MODELS: list[dict[str, Any]] = [
    {
        "id": "claude-haiku-4-5-20251001",
        "label": "Claude Haiku 4.5",
        "tier": "Cheapest & fastest",
        "description": "Lowest cost per turn. Good default for most agent chat.",
        "recommended": True,
    },
    {
        "id": "claude-sonnet-5",
        "label": "Claude Sonnet 5",
        "tier": "Balanced",
        "description": "More capable than Haiku, higher cost per turn.",
        "recommended": False,
    },
    {
        "id": "claude-opus-4-8",
        "label": "Claude Opus 4.8",
        "tier": "Most capable",
        "description": "Highest cost. Reserve for agents doing hard reasoning work.",
        "recommended": False,
    },
    {
        "id": "claude-fable-5",
        "label": "Claude Fable 5",
        "tier": "Claude 5 family, alternative to Sonnet",
        "description": "Similar cost tier to Sonnet 5. Try it if an agent's voice fits it better.",
        "recommended": False,
    },
]

DEFAULT_MODEL_ID = "claude-haiku-4-5-20251001"


class SettingsError(Exception):
    pass


def _read_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT settings_json FROM workspace LIMIT 1").fetchone()
    if row is None:
        raise SettingsError("No workspace found")
    raw = row["settings_json"]
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_settings(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE workspace SET settings_json = ?, updated_at = ? "
        "WHERE id = (SELECT id FROM workspace LIMIT 1)",
        (json.dumps(data, separators=(",", ":")), utc_now_iso()),
    )
    conn.commit()


def get_llm_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    data = _read_settings(conn)
    llm = data.get("llm") if isinstance(data.get("llm"), dict) else {}
    model_id = str(llm.get("default_model") or DEFAULT_MODEL_ID)
    return {
        "default_model": model_id,
        "available_models": AVAILABLE_MODELS,
    }


def save_llm_settings(conn: sqlite3.Connection, *, default_model: str) -> dict[str, Any]:
    if not default_model.strip():
        raise SettingsError("Model id cannot be empty")
    data = _read_settings(conn)
    llm = data.get("llm") if isinstance(data.get("llm"), dict) else {}
    llm["default_model"] = default_model
    data["llm"] = llm
    _write_settings(conn, data)
    return get_llm_settings(conn)
