from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pidgin.db import apply_migrations, connect
from pidgin.db.change_probe import ALL_SOURCES, agent_gating_config, probe_changes, total_changes
from pidgin.db.timers import count_wakeups_today, create_timer
from pidgin.runtime.scheduler import fire_due_timers
from pidgin.util.ids import new_ulid, utc_now_iso

BASELINE = "2026-07-10T00:00:00.000Z"
AFTER = "2026-07-10T12:00:00.000Z"  # after the baseline
BEFORE = "2026-07-09T12:00:00.000Z"  # before the baseline


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db = connect(tmp_path / "db.sqlite")
    apply_migrations(db)
    return db


def _agent(conn: sqlite3.Connection, *, agent_id: str = "agent1", gating: int = 1,
           sources_json: str | None = None) -> str:
    """Insert a minimal active agent + its principal."""
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO ai_employees (
          id, display_name, role_title, handle, recipe_snapshot_id,
          human_owner_principal_id, current_status, change_gating_enabled,
          change_sources_json, created_at, updated_at
        ) VALUES (?, 'Sam', 'Support', ?, 'rs', 'owner', 'active', ?, ?, ?, ?)
        """,
        (agent_id, agent_id, gating, sources_json, now, now),
    )
    conn.execute(
        """
        INSERT INTO principals (id, type, display_name, ai_employee_id,
          is_active, created_at, updated_at)
        VALUES (?, 'pidgin_agent', 'Sam', ?, 1, ?, ?)
        """,
        (f"p_{agent_id}", agent_id, now, now),
    )
    conn.commit()
    return agent_id


def _recurring(conn: sqlite3.Connection, *, agent_id: str = "agent1",
               baseline: str | None = BASELINE, always_run: bool = False) -> str:
    tid = create_timer(
        conn,
        ai_employee_id=agent_id,
        scheduled_at="2020-01-01T00:00:00.000Z",  # already due
        reason="heartbeat",
        inherited_trust_label="internal-authenticated",
        originating_turn_id=None,
        kind="recurring",
        recurrence_json=json.dumps({"kind": "interval", "every_minutes": 30}),
        always_run=always_run,
    )
    if baseline is not None:
        conn.execute("UPDATE agent_timers SET last_ran_at = ? WHERE id = ?", (baseline, tid))
        conn.commit()
    return tid


def _inbound(conn: sqlite3.Connection, *, agent_id: str, trigger: str, received_at: str,
             status: str = "done") -> None:
    conn.execute(
        """
        INSERT INTO inbound_events (id, trigger_type, target_ai_employee_id, trust_label,
          payload_json, processing_status, received_at)
        VALUES (?, ?, ?, 'internal-authenticated', '{}', ?, ?)
        """,
        (new_ulid(), trigger, agent_id, status, received_at),
    )
    conn.commit()


def _skipped_turns(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM turns WHERE current_status = 'skipped'").fetchall())


# --- the probe ---------------------------------------------------------------


def test_probe_counts_each_source(conn: sqlite3.Connection) -> None:
    agent = _agent(conn)
    # source 1: a DM after baseline (counts even though already processed)
    _inbound(conn, agent_id=agent, trigger="direct_address", received_at=AFTER)
    # source 4: a watcher firing after baseline
    _inbound(conn, agent_id=agent, trigger="watcher", received_at=AFTER)
    # source 5: a delegated return after baseline
    _inbound(conn, agent_id=agent, trigger="peer_delegation", received_at=AFTER)
    # a timer firing is NOT a change — must not count
    _inbound(conn, agent_id=agent, trigger="timer", received_at=AFTER)
    # source 2: a task status-log entry after baseline
    tid = new_ulid()
    conn.execute(
        "INSERT INTO tasks (id, title, owner_principal_id, current_status, created_at, updated_at) "
        "VALUES (?, 'x', ?, 'open', ?, ?)",
        (tid, f"p_{agent}", BASELINE, BASELINE),
    )
    conn.execute(
        "INSERT INTO tasks_status_log (id, task_id, to_status, actor_principal_id, occurred_at) "
        "VALUES (?, ?, 'in_progress', ?, ?)",
        (new_ulid(), tid, f"p_{agent}", AFTER),
    )
    # source 3: an approval resolved after baseline
    conn.execute(
        """
        INSERT INTO pending_approvals (id, ai_employee_id, originating_turn_id, proposed_action,
          proposed_action_params_json, trust_label, requesting_principal_id,
          requires_approver_principal_id, current_status, resolved_at, created_at)
        VALUES (?, ?, 't', 'post', '{}', 'internal-authenticated', 'p', 'p', 'approved', ?, ?)
        """,
        (new_ulid(), agent, AFTER, BASELINE),
    )
    conn.commit()

    snapshot = probe_changes(conn, ai_employee_id=agent, since=BASELINE)
    assert snapshot == {
        "inbound_events": 1,
        "task_state": 1,
        "approvals": 1,
        "watched_resources": 1,
        "delegated_returns": 1,
    }
    assert total_changes(snapshot) == 5


def test_probe_ignores_changes_before_baseline(conn: sqlite3.Connection) -> None:
    agent = _agent(conn)
    _inbound(conn, agent_id=agent, trigger="direct_address", received_at=BEFORE)
    snapshot = probe_changes(conn, ai_employee_id=agent, since=BASELINE)
    assert total_changes(snapshot) == 0


def test_probe_due_at_crossing_counts(conn: sqlite3.Connection) -> None:
    agent = _agent(conn)
    # A task whose due_at falls in (baseline, now] — a deadline that just passed.
    conn.execute(
        "INSERT INTO tasks (id, title, owner_principal_id, current_status, due_at, "
        "created_at, updated_at) VALUES (?, 'due', ?, 'open', ?, ?, ?)",
        (new_ulid(), f"p_{agent}", AFTER, BASELINE, BASELINE),
    )
    conn.commit()
    snapshot = probe_changes(conn, ai_employee_id=agent, since=BASELINE, now=utc_now_iso())
    assert snapshot["task_state"] == 1


def test_probe_respects_disabled_sources(conn: sqlite3.Connection) -> None:
    agent = _agent(conn)
    _inbound(conn, agent_id=agent, trigger="direct_address", received_at=AFTER)
    snapshot = probe_changes(conn, ai_employee_id=agent, since=BASELINE,
                             sources=("task_state", "approvals"))
    assert "inbound_events" not in snapshot
    assert total_changes(snapshot) == 0


# --- the gate in fire_due_timers ---------------------------------------------


def test_recurring_skips_when_nothing_changed(conn: sqlite3.Connection) -> None:
    agent = _agent(conn)
    tid = _recurring(conn, agent_id=agent)

    # No changes since baseline → skip. Returns 0 real wakeups.
    assert fire_due_timers(conn) == 0

    skipped = _skipped_turns(conn)
    assert len(skipped) == 1
    snap = json.loads(skipped[0]["probe_snapshot_json"])
    assert snap["baseline"] == BASELINE
    assert snap["counts"] == {k: 0 for k in ALL_SOURCES}

    # The anchor event is 'skipped' (never dispatched) and points at the turn.
    ev = conn.execute("SELECT * FROM inbound_events WHERE trigger_type='timer'").fetchone()
    assert ev["processing_status"] == "skipped"
    assert ev["resulting_turn_id"] == skipped[0]["id"]

    # Baseline is unchanged (a skip never advances it) and the timer re-armed.
    row = conn.execute("SELECT * FROM agent_timers WHERE id = ?", (tid,)).fetchone()
    assert row["last_ran_at"] == BASELINE
    assert row["status"] == "pending"
    assert row["scheduled_at"] > "2020-01-01T00:00:00.000Z"

    # A skip draws no wakeup budget.
    assert count_wakeups_today(conn, ai_employee_id=agent) == 0


def test_recurring_runs_when_something_changed(conn: sqlite3.Connection) -> None:
    agent = _agent(conn)
    tid = _recurring(conn, agent_id=agent)
    _inbound(conn, agent_id=agent, trigger="direct_address", received_at=AFTER)

    assert fire_due_timers(conn) == 1
    assert _skipped_turns(conn) == []
    # A real (pending) wakeup event exists and the baseline advanced past it.
    ev = conn.execute(
        "SELECT * FROM inbound_events WHERE trigger_type='timer' AND processing_status='pending'"
    ).fetchone()
    assert ev is not None
    row = conn.execute("SELECT last_ran_at FROM agent_timers WHERE id = ?", (tid,)).fetchone()
    assert row["last_ran_at"] > BASELINE


def test_always_run_timer_never_skips(conn: sqlite3.Connection) -> None:
    agent = _agent(conn)
    _recurring(conn, agent_id=agent, always_run=True)  # the daily floor
    # Nothing changed, but always_run bypasses the gate.
    assert fire_due_timers(conn) == 1
    assert _skipped_turns(conn) == []


def test_first_fire_runs_when_no_baseline(conn: sqlite3.Connection) -> None:
    agent = _agent(conn)
    tid = _recurring(conn, agent_id=agent, baseline=None)  # never ran before
    assert fire_due_timers(conn) == 1
    assert _skipped_turns(conn) == []
    # First real run stamps the baseline.
    row = conn.execute("SELECT last_ran_at FROM agent_timers WHERE id = ?", (tid,)).fetchone()
    assert row["last_ran_at"] is not None


def test_gating_disabled_agent_never_skips(conn: sqlite3.Connection) -> None:
    agent = _agent(conn, gating=0)
    _recurring(conn, agent_id=agent)
    enabled, _ = agent_gating_config(conn, agent)
    assert enabled is False
    # Gating off → every recurring wakeup runs, even with nothing changed.
    assert fire_due_timers(conn) == 1
    assert _skipped_turns(conn) == []


# --- guaranteed daily wake floor ---------------------------------------------


def test_guaranteed_wake_floor_default(conn: sqlite3.Connection) -> None:
    from pidgin.services.activation import _arm_guaranteed_wakes

    agent = _agent(conn)  # guaranteed_wake_times_json is NULL → default ["09:00"]
    assert _arm_guaranteed_wakes(conn, agent) == 1
    row = conn.execute(
        "SELECT recurrence_json, always_run, kind FROM agent_timers WHERE ai_employee_id = ?",
        (agent,),
    ).fetchone()
    assert row["kind"] == "recurring"
    assert row["always_run"] == 1  # the floor is never gated
    rec = json.loads(row["recurrence_json"])
    assert rec == {"kind": "daily", "at_local_time": "09:00"}


def test_guaranteed_wake_floor_multiple_times(conn: sqlite3.Connection) -> None:
    from pidgin.services.activation import _arm_guaranteed_wakes

    agent = _agent(conn, sources_json=None)
    conn.execute(
        "UPDATE ai_employees SET guaranteed_wake_times_json = ? WHERE id = ?",
        (json.dumps(["09:00", "13:00", "17:00"]), agent),
    )
    conn.commit()
    assert _arm_guaranteed_wakes(conn, agent) == 3
    times = {
        json.loads(r["recurrence_json"])["at_local_time"]
        for r in conn.execute(
            "SELECT recurrence_json FROM agent_timers WHERE ai_employee_id = ? AND always_run = 1",
            (agent,),
        )
    }
    assert times == {"09:00", "13:00", "17:00"}
