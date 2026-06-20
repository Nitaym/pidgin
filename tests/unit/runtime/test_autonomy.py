from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from pidgin.db import apply_migrations, connect
from pidgin.db.tasks import create_task, list_open_tasks, set_task_status
from pidgin.db.timers import (
    count_pending_timers,
    create_timer,
    list_due_timers,
    next_occurrence,
)
from pidgin.runtime.actions import execute_action
from pidgin.runtime.scheduler import fire_due_timers
from pidgin.types import ActionType, ProposedAction, TrustLabel


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db = connect(tmp_path / "db.sqlite")
    apply_migrations(db)
    return db


def _ctx(conn: sqlite3.Connection, *, max_pending: int | None = None) -> SimpleNamespace:
    limits = SimpleNamespace(max_pending_timers=max_pending, max_wakeups_per_day=None)
    autonomy = SimpleNamespace(limits=limits) if max_pending else None
    return SimpleNamespace(
        workspace=SimpleNamespace(db_bridge=conn),
        agent=SimpleNamespace(
            agent_id="agent1",
            agent_principal_id="p1",
            handle="sam",
            display_name="Sam",
            role_title="Support",
            recipe=SimpleNamespace(autonomy=autonomy),
        ),
        event=SimpleNamespace(trust_label=TrustLabel.INTERNAL_AUTHENTICATED),
        turn=SimpleNamespace(id="turn1"),
        egress=None,
        invocation_id=None,
    )


# --- recurrence math ---------------------------------------------------------


def test_daily_recurrence_rolls_to_tomorrow_when_past() -> None:
    from datetime import UTC, datetime

    after = datetime(2026, 6, 20, 18, 0, tzinfo=UTC)
    nxt = next_occurrence({"kind": "daily", "at_local_time": "09:00"}, after=after)
    assert nxt.isoformat() == "2026-06-21T09:00:00+00:00"


def test_unknown_recurrence_kind_raises() -> None:
    from datetime import UTC, datetime

    with pytest.raises(ValueError):
        next_occurrence({"kind": "monthly"}, after=datetime(2026, 1, 1, tzinfo=UTC))


# --- recurring timer re-arms instead of terminating --------------------------


def test_recurring_timer_rearms_on_fire(conn: sqlite3.Connection) -> None:
    timer_id = create_timer(
        conn,
        ai_employee_id="agent1",
        scheduled_at="2020-01-01T00:00:00.000Z",
        reason="daily review",
        inherited_trust_label="internal-authenticated",
        kind="recurring",
        recurrence_json=json.dumps({"kind": "interval", "every_minutes": 60}),
    )
    assert fire_due_timers(conn) == 1
    row = conn.execute("SELECT * FROM agent_timers WHERE id = ?", (timer_id,)).fetchone()
    # Still pending, advanced to a future time — not terminally fired.
    assert row["status"] == "pending"
    assert row["scheduled_at"] > "2020-01-01T00:00:00.000Z"
    # And it doesn't immediately re-fire.
    assert fire_due_timers(conn) == 0


def test_self_anchored_bootstrap_fires_without_conversation(conn: sqlite3.Connection) -> None:
    create_timer(
        conn,
        ai_employee_id="agent1",
        scheduled_at="2020-01-01T00:00:00.000Z",
        reason="[Activation] set yourself up",
        inherited_trust_label="internal-authenticated",
        originating_turn_id=None,
        kind="bootstrap",
    )
    assert fire_due_timers(conn) == 1
    event = conn.execute(
        "SELECT * FROM inbound_events WHERE trigger_type = 'timer'"
    ).fetchone()
    payload = json.loads(event["payload_json"])
    # Bootstrap reason is delivered verbatim (no follow-up wrapper).
    assert payload["message_text"] == "[Activation] set yourself up"
    assert event["trust_label"] == "internal-authenticated"


# --- schedule_self recurrence + budget --------------------------------------


def test_schedule_self_creates_recurring(conn: sqlite3.Connection) -> None:
    ctx = _ctx(conn)
    action = ProposedAction(
        action_type=ActionType.SCHEDULE_SELF,
        params={"reason": "weekly report", "recurrence": {"kind": "weekly", "weekday": "fri"}},
    )
    result = execute_action(ctx, action)  # type: ignore[arg-type]
    assert "Recurring wake-up" in result
    row = conn.execute("SELECT kind, recurrence_json FROM agent_timers").fetchone()
    assert row["kind"] == "recurring"
    assert json.loads(row["recurrence_json"])["weekday"] == "fri"


def test_schedule_self_respects_pending_budget(conn: sqlite3.Connection) -> None:
    ctx = _ctx(conn, max_pending=1)
    mk = lambda r: ProposedAction(  # noqa: E731
        action_type=ActionType.SCHEDULE_SELF, params={"delay_minutes": 5, "reason": r}
    )
    assert execute_action(ctx, mk("first")).startswith("Scheduled wake-up")  # type: ignore[arg-type]
    over = execute_action(ctx, mk("second"))  # type: ignore[arg-type]
    assert "maximum number of pending" in over
    assert count_pending_timers(conn, ai_employee_id="agent1") == 1


# --- task backlog actions ----------------------------------------------------


def test_open_and_close_task_actions(conn: sqlite3.Connection) -> None:
    ctx = _ctx(conn)
    opened = execute_action(  # type: ignore[arg-type]
        ctx,
        ProposedAction(action_type=ActionType.OPEN_TASK, params={"title": "Refresh competitor scan"}),
    )
    assert opened.startswith("Opened task")
    tasks = list_open_tasks(conn, owner_principal_id="p1")
    assert len(tasks) == 1
    task_id = tasks[0]["id"]

    closed = execute_action(  # type: ignore[arg-type]
        ctx,
        ProposedAction(action_type=ActionType.CLOSE, params={"task_id": task_id, "outcome": "done"}),
    )
    assert task_id in closed
    assert list_open_tasks(conn, owner_principal_id="p1") == []


def test_set_task_status_rejects_foreign_owner(conn: sqlite3.Connection) -> None:
    task_id = create_task(conn, owner_principal_id="p1", title="mine")
    assert set_task_status(conn, task_id=task_id, owner_principal_id="someone-else", to_status="done") is False
    assert set_task_status(conn, task_id=task_id, owner_principal_id="p1", to_status="done") is True
