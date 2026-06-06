from __future__ import annotations

import json
from pathlib import Path

import pytest

from pidgin.db import apply_migrations, connect, init_workspace_db
from pidgin.hire import hire_support_agent
from pidgin.services.chat import get_conversation_messages, send_chat_message
from pidgin.util.slug import slugify
from pidgin.workspace import create_workspace


@pytest.fixture
def pidgin_home(tmp_path: Path) -> Path:
    return tmp_path / ".pidgin"


@pytest.fixture
def recipe_path() -> Path:
    return Path(__file__).resolve().parents[2] / "recipes" / "support-agent-v0.1.json"


def test_chat_turn_persists_reply_and_invocation(
    pidgin_home: Path,
    recipe_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIDGIN_LLM_BACKEND", "stub")

    paths = create_workspace("Chat Co", "pw", slugify("Chat Co"), home=pidgin_home)
    auth = json.loads(paths.auth_json.read_text(encoding="utf-8"))
    conn = connect(paths.db_sqlite)
    apply_migrations(conn)
    init_workspace_db(conn, auth["workspace_id"], "Chat Co")

    hire_result = hire_support_agent(conn, paths_root=paths.root, recipe_path=recipe_path)
    conversation_id = hire_result["conversation_id"]
    assert conversation_id

    _message_id, event_id, _conv = send_chat_message(
        conn,
        agent_handle=hire_result["handle"],
        body_text="hello",
        run_turn=True,
    )
    assert event_id

    event = conn.execute(
        "SELECT processing_status, resulting_turn_id FROM inbound_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    assert event is not None
    assert event["processing_status"] == "done"
    turn_id = event["resulting_turn_id"]
    assert turn_id

    invocations = conn.execute(
        "SELECT id, provider, model_id FROM model_invocations WHERE turn_id = ?",
        (turn_id,),
    ).fetchall()
    assert len(invocations) == 1
    assert invocations[0]["provider"] == "stub"

    conversation = conn.execute(
        "SELECT id FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    assert conversation is not None
    messages = get_conversation_messages(conn, conversation["id"])
    assert len(messages) >= 2
    assert messages[0]["body_text"] == "hello"
    assert messages[-1]["sender_display_name"] == hire_result["display_name"]
    assert "help" in messages[-1]["body_text"].lower()
