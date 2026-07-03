from __future__ import annotations

import json
from pathlib import Path

import pytest

from pidgin.db import apply_migrations, connect, init_workspace_db
from pidgin.db.employees import list_agents
from pidgin.hire import HireRequest, hire_from_recipe
from pidgin.knowledge.memory import recall_tail, remember
from pidgin.services.reset import reset_workspace_memory
from pidgin.util.slug import slugify
from pidgin.workspace import create_workspace


@pytest.fixture
def pidgin_home(tmp_path: Path) -> Path:
    return tmp_path / ".pidgin"


@pytest.fixture
def recipe_path() -> Path:
    return Path(__file__).resolve().parents[2] / "recipes" / "support-agent-v0.1.json"


def test_reset_workspace_memory_wipes_agents_and_journals(
    pidgin_home: Path, recipe_path: Path
) -> None:
    paths = create_workspace("Acme", "pw", slugify("Acme"), home=pidgin_home)
    auth = json.loads(paths.auth_json.read_text(encoding="utf-8"))
    conn = connect(paths.db_sqlite)
    apply_migrations(conn)
    init_workspace_db(conn, auth["workspace_id"], "Acme")

    hired = hire_from_recipe(
        conn,
        paths,
        HireRequest(display_name="Support", recipe_path=recipe_path),
    )
    conn.commit()
    remember(paths, "support", "learned something important")
    assert recall_tail(paths, "support") != ""

    conversation_id = "conv-1"
    ts = "2026-01-01T00:00:00Z"
    conn.execute(
        """
        INSERT INTO conversations
          (id, ai_employee_id, modality, started_at, created_at, updated_at)
        VALUES (?, ?, 'chat', ?, ?, ?)
        """,
        (conversation_id, hired.ai_employee_id, ts, ts, ts),
    )
    conn.commit()

    reseeded = reset_workspace_memory(conn, paths)

    handles_after = {agent["handle"] for agent in list_agents(conn, include_archived=True)}
    assert "support" not in handles_after
    assert handles_after == set(reseeded)
    assert conn.execute(
        "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone() is None
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM principals WHERE type = 'workspace_member'"
    ).fetchone()["n"] == 1
    assert recall_tail(paths, "support") == ""
    assert reseeded

    workspace_row = conn.execute("SELECT display_name FROM workspace LIMIT 1").fetchone()
    assert workspace_row["display_name"] == "Acme"
