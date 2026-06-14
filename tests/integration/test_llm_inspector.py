from __future__ import annotations

import json
from pathlib import Path

import pytest

from pidgin.db import apply_migrations, connect, init_workspace_db
from pidgin.db.diagnostics import list_model_invocations
from pidgin.hire import hire_support_agent
from pidgin.services.chat import send_chat_message
from pidgin.util.slug import slugify
from pidgin.workspace import create_workspace


@pytest.fixture
def pidgin_home(tmp_path: Path) -> Path:
    return tmp_path / ".pidgin"


@pytest.fixture
def recipe_path() -> Path:
    return Path(__file__).resolve().parents[2] / "recipes" / "support-agent-v0.1.json"


def test_list_model_invocations_returns_full_request_and_response(
    pidgin_home: Path,
    recipe_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIDGIN_LLM_BACKEND", "stub")

    paths = create_workspace("Inspect Co", "pw", slugify("Inspect Co"), home=pidgin_home)
    auth = json.loads(paths.auth_json.read_text(encoding="utf-8"))
    conn = connect(paths.db_sqlite)
    apply_migrations(conn)
    init_workspace_db(conn, auth["workspace_id"], "Inspect Co")

    hire_result = hire_support_agent(conn, paths_root=paths.root, recipe_path=recipe_path)
    send_chat_message(
        conn,
        agent_handle=hire_result["handle"],
        body_text="hello",
        run_turn=True,
    )

    rows = list_model_invocations(conn)
    assert len(rows) == 1
    row = rows[0]

    assert row["agent_display_name"] == hire_result["display_name"]
    assert row["agent_handle"] == hire_result["handle"]
    assert row["source"] == "pidgin_chat"
    assert row["provider"] == "stub"

    # Full request payload, parsed: system prompt first, user message last.
    roles = [m["role"] for m in row["request_messages"]]
    assert roles[0] == "system"
    assert roles[-1] == "user"
    assert row["request_messages"][-1]["content"] == "hello"
    assert isinstance(row["request_tools"], list)

    # Full response payload, parsed.
    assert row["response"]["stop_reason"] in {"end_turn", "tool_use"}

    # Cursor: nothing newer than the newest id.
    assert list_model_invocations(conn, after=row["id"]) == []

    send_chat_message(
        conn,
        agent_handle=hire_result["handle"],
        body_text="second message",
        run_turn=True,
    )
    newer = list_model_invocations(conn, after=row["id"])
    assert len(newer) == 1
    assert newer[0]["id"] != row["id"]
    assert newer[0]["request_messages"][-1]["content"] == "second message"
