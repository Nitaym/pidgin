from __future__ import annotations

import json
from pathlib import Path

import pytest

from pidgin.db import apply_migrations, connect, init_workspace_db
from pidgin.hire import HireRequest, hire_from_recipe
from pidgin.services.activation import activate_agent
from pidgin.util.slug import slugify
from pidgin.workspace import create_workspace


@pytest.fixture
def pidgin_home(tmp_path: Path) -> Path:
    return tmp_path / ".pidgin"


@pytest.fixture
def recipe_path() -> Path:
    return Path(__file__).resolve().parents[2] / "recipes" / "marketing-agent-v0.1.json"


def _workspace(pidgin_home: Path):
    paths = create_workspace("Acme", "pw", slugify("Acme"), home=pidgin_home)
    auth = json.loads(paths.auth_json.read_text(encoding="utf-8"))
    conn = connect(paths.db_sqlite)
    apply_migrations(conn)
    init_workspace_db(conn, auth["workspace_id"], "Acme")
    return paths, conn


def test_activation_enqueues_self_anchored_bootstrap(pidgin_home: Path, recipe_path: Path) -> None:
    paths, conn = _workspace(pidgin_home)
    hired = hire_from_recipe(conn, paths, HireRequest(display_name="VP Marketing", recipe_path=recipe_path))

    result = activate_agent(conn, handle="vp-marketing")
    assert result["current_status"] == "active"
    assert result["bootstrapped"] == "true"

    timer = conn.execute(
        "SELECT * FROM agent_timers WHERE ai_employee_id = ?", (hired.ai_employee_id,)
    ).fetchone()
    assert timer is not None
    assert timer["kind"] == "bootstrap"
    assert timer["originating_turn_id"] is None  # self-anchored
    assert timer["inherited_trust_label"] == "internal-authenticated"
    # The recipe's cadence guidance reached the brief.
    assert "content pipeline" in timer["reason"]
    assert "report to your operator" in timer["reason"].lower()
    # Every agent is told to arm the 30-minute task heartbeat that drives its
    # backlog to completion without being prompted.
    assert '"every_minutes": 30' in timer["reason"]

    emp = conn.execute(
        "SELECT bootstrapped_at, current_status FROM ai_employees WHERE id = ?",
        (hired.ai_employee_id,),
    ).fetchone()
    assert emp["bootstrapped_at"]
    assert emp["current_status"] == "active"


def test_reactivation_does_not_rebootstrap(pidgin_home: Path, recipe_path: Path) -> None:
    paths, conn = _workspace(pidgin_home)
    hire_from_recipe(conn, paths, HireRequest(display_name="VP Marketing", recipe_path=recipe_path))

    activate_agent(conn, handle="vp-marketing")
    second = activate_agent(conn, handle="vp-marketing")
    assert second["bootstrapped"] == "false"

    count = conn.execute(
        "SELECT COUNT(*) AS n FROM agent_timers WHERE kind = 'bootstrap'"
    ).fetchone()["n"]
    assert count == 1


def test_activate_unknown_agent_raises(pidgin_home: Path) -> None:
    _, conn = _workspace(pidgin_home)
    from pidgin.services.activation import ActivationError

    with pytest.raises(ActivationError):
        activate_agent(conn, handle="nobody")


def test_deactivate_stops_agent_and_cancels_timers(pidgin_home: Path, recipe_path: Path) -> None:
    from pidgin.services.activation import deactivate_agent

    paths, conn = _workspace(pidgin_home)
    hired = hire_from_recipe(
        conn, paths, HireRequest(display_name="VP Marketing", recipe_path=recipe_path)
    )
    activate_agent(conn, handle="vp-marketing")

    result = deactivate_agent(conn, handle="vp-marketing")
    assert result["current_status"] == "draft"
    # The bootstrap timer + one ungated guaranteed daily wake (the change-gating
    # floor, armed at activation) — both cancelled on deactivation.
    assert result["timers_cancelled"] == "2"

    emp = conn.execute(
        "SELECT bootstrapped_at, current_status FROM ai_employees WHERE id = ?",
        (hired.ai_employee_id,),
    ).fetchone()
    assert emp["current_status"] == "draft"
    assert emp["bootstrapped_at"] is None  # cleared so a later activate re-bootstraps

    pending = conn.execute(
        "SELECT COUNT(*) AS n FROM agent_timers WHERE ai_employee_id = ? AND status = 'pending'",
        (hired.ai_employee_id,),
    ).fetchone()["n"]
    assert pending == 0


def test_deactivate_then_reactivate_rebootstraps(pidgin_home: Path, recipe_path: Path) -> None:
    from pidgin.services.activation import deactivate_agent

    paths, conn = _workspace(pidgin_home)
    hire_from_recipe(
        conn, paths, HireRequest(display_name="VP Marketing", recipe_path=recipe_path)
    )
    activate_agent(conn, handle="vp-marketing")
    deactivate_agent(conn, handle="vp-marketing")

    again = activate_agent(conn, handle="vp-marketing")
    assert again["current_status"] == "active"
    assert again["bootstrapped"] == "true"  # cleared marker → fresh bootstrap

    live = conn.execute(
        "SELECT COUNT(*) AS n FROM agent_timers WHERE status = 'pending' AND kind = 'bootstrap'"
    ).fetchone()["n"]
    assert live == 1


def test_deactivate_non_active_raises(pidgin_home: Path, recipe_path: Path) -> None:
    from pidgin.services.activation import ActivationError, deactivate_agent

    paths, conn = _workspace(pidgin_home)
    hire_from_recipe(
        conn, paths, HireRequest(display_name="VP Marketing", recipe_path=recipe_path)
    )
    # Never activated → still draft.
    with pytest.raises(ActivationError):
        deactivate_agent(conn, handle="vp-marketing")
