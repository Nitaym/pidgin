from __future__ import annotations

import json
from pathlib import Path

import pytest

from pidgin.db import apply_migrations, connect, init_workspace_db
from pidgin.hire import (
    HireRequest,
    get_hr_agent,
    hire_from_recipe,
    hire_support_agent,
    load_seed_manifest,
    seed_workspace_agents,
)
from pidgin.recipes import bundle_sha256, load_role_recipe, resolve_permission_profile
from pidgin.util.slug import slugify
from pidgin.workspace import create_workspace


@pytest.fixture
def pidgin_home(tmp_path: Path) -> Path:
    return tmp_path / ".pidgin"


@pytest.fixture
def recipe_path() -> Path:
    return Path(__file__).resolve().parents[2] / "recipes" / "support-agent-v0.1.json"


def test_hire_support_agent(pidgin_home: Path, recipe_path: Path) -> None:
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

    employee = conn.execute(
        "SELECT * FROM ai_employees WHERE id = ?",
        (hired.ai_employee_id,),
    ).fetchone()
    assert employee is not None
    assert employee["display_name"] == "Support"
    assert employee["handle"] == "support"
    assert employee["current_status"] == "draft"
    assert employee["recipe_snapshot_id"] == hired.recipe_snapshot_id

    snapshot = conn.execute(
        "SELECT * FROM ai_employee_recipe_snapshots WHERE id = ?",
        (hired.recipe_snapshot_id,),
    ).fetchone()
    assert snapshot is not None
    assert snapshot["recipe_id"] == "support-agent"
    assert snapshot["recipe_version"] == "0.1.0"
    assert snapshot["ai_employee_id"] == hired.ai_employee_id

    recipe = load_role_recipe(recipe_path)
    assert snapshot["bundle_sha256"] == bundle_sha256(recipe)

    principal = conn.execute(
        "SELECT * FROM principals WHERE ai_employee_id = ?",
        (hired.ai_employee_id,),
    ).fetchone()
    assert principal is not None
    assert principal["type"] == "pidgin_agent"
    assert principal["id"] == hired.principal_id

    assert paths.agent_memory_dir("support").is_dir()


def test_hire_support_agent_creates_conversation(pidgin_home: Path, recipe_path: Path) -> None:
    paths = create_workspace("Acme", "pw", slugify("Acme"), home=pidgin_home)
    auth = json.loads(paths.auth_json.read_text(encoding="utf-8"))
    conn = connect(paths.db_sqlite)
    apply_migrations(conn)
    init_workspace_db(conn, auth["workspace_id"], "Acme")

    result = hire_support_agent(conn, paths_root=paths.root, recipe_path=recipe_path)
    assert result["conversation_id"]
    assert result["handle"] == "support"

    conversation = conn.execute(
        "SELECT ai_employee_id FROM conversations WHERE id = ?",
        (result["conversation_id"],),
    ).fetchone()
    assert conversation is not None
    assert conversation["ai_employee_id"] == result["ai_employee_id"]


def test_seed_manifest_lists_hr_and_enablement_agents() -> None:
    seeds = load_seed_manifest()
    by_recipe = {seed.recipe_id: seed for seed in seeds}
    assert by_recipe["hr-onboarding"].handle == "hr"
    assert by_recipe["enablement"].handle == "enablement"


def test_seed_workspace_agents_is_idempotent(pidgin_home: Path) -> None:
    paths = create_workspace("Acme", "pw", slugify("Acme"), home=pidgin_home)
    auth = json.loads(paths.auth_json.read_text(encoding="utf-8"))
    conn = connect(paths.db_sqlite)
    apply_migrations(conn)
    init_workspace_db(conn, auth["workspace_id"], "Acme")

    assert get_hr_agent(conn) is None

    hired = seed_workspace_agents(conn, paths_root=paths.root)
    assert "hr" in hired
    assert "enablement" in hired

    agent = get_hr_agent(conn)
    assert agent is not None
    assert agent["handle"] == "hr"

    # Re-running seeding must not duplicate the singleton agents.
    again = seed_workspace_agents(conn, paths_root=paths.root)
    assert again == []
    for handle in ("hr", "enablement"):
        rows = conn.execute(
            "SELECT id FROM ai_employees WHERE handle = ?", (handle,)
        ).fetchall()
        assert len(rows) == 1


def test_reconcile_backfills_existing_workspace(pidgin_home: Path) -> None:
    # A workspace seeded with only HR (as if created before Enablement existed)
    # gains Enablement on the next reconciliation pass, without duplicating HR.
    from pidgin.hire import TemplateHireRequest, hire_with_template
    from pidgin.services.workspace import reconcile_workspace_agents

    paths = create_workspace("Acme", "pw", slugify("Acme"), home=pidgin_home)
    auth = json.loads(paths.auth_json.read_text(encoding="utf-8"))
    conn = connect(paths.db_sqlite)
    apply_migrations(conn)
    init_workspace_db(conn, auth["workspace_id"], "Acme")
    hire_with_template(
        conn,
        paths_root=paths.root,
        request=TemplateHireRequest(
            template_source="bundled", template_id="hr-onboarding", handle="hr"
        ),
    )
    conn.close()

    results = reconcile_workspace_agents(home=pidgin_home)
    assert results[slugify("Acme")] == ["enablement"]

    conn = connect(paths.db_sqlite)
    handles = {
        row["handle"]
        for row in conn.execute("SELECT handle FROM ai_employees").fetchall()
    }
    assert {"hr", "enablement"} <= handles

    # Converged: a second pass hires nothing.
    assert reconcile_workspace_agents(home=pidgin_home)[slugify("Acme")] == []


def test_resolve_permission_profile_from_recipe(recipe_path: Path) -> None:
    recipe = load_role_recipe(recipe_path)
    profile = resolve_permission_profile(recipe)
    assert "execute" in profile.requires_approval
    assert "read" in profile.can_read
    assert "say" in profile.can_write
