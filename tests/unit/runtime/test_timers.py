from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from types import SimpleNamespace

from pidgin.db import apply_migrations, connect
from pidgin.db.timers import create_timer, find_pending_timer_near, list_due_timers
from pidgin.runtime.actions import execute_action
from pidgin.runtime.scheduler import fire_due_timers
from pidgin.types import ActionType, ProposedAction, TrustLabel


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db = connect(tmp_path / "db.sqlite")
    apply_migrations(db)
    return db


def _timer(conn: sqlite3.Connection, *, scheduled_at: str) -> str:
    return create_timer(
        conn,
        ai_employee_id="agent1",
        scheduled_at=scheduled_at,
        reason="Follow up with Dana about the launch",
        originating_turn_id="turn1",
        inherited_trust_label="internal-authenticated",
    )


def test_future_timer_is_not_due(conn: sqlite3.Connection) -> None:
    _timer(conn, scheduled_at="2999-01-01T00:00:00.000Z")
    assert list_due_timers(conn) == []
    assert fire_due_timers(conn) == 0


def test_due_timer_fires_inbound_event(conn: sqlite3.Connection) -> None:
    timer_id = _timer(conn, scheduled_at="2020-01-01T00:00:00.000Z")
    fired = fire_due_timers(conn)
    assert fired == 1

    timer = conn.execute("SELECT * FROM agent_timers WHERE id = ?", (timer_id,)).fetchone()
    assert timer["status"] == "fired"
    assert timer["fired_event_id"]

    event = conn.execute(
        "SELECT * FROM inbound_events WHERE id = ?", (timer["fired_event_id"],)
    ).fetchone()
    assert event["trigger_type"] == "timer"
    assert event["target_ai_employee_id"] == "agent1"
    payload = json.loads(event["payload_json"])
    assert "Follow up with Dana" in payload["message_text"]
    assert payload["timer_id"] == timer_id


def test_timer_event_inherits_slack_origin_context(conn: sqlite3.Connection) -> None:
    origin_payload = {
        "connector_type": "slack",
        "connector_installation_id": "inst1",
        "external_channel_id": "C100",
        "external_thread_id": "1718.0001",
        "message_text": "remind me in 2 minutes",
    }
    conn.execute(
        """
        INSERT INTO principals (id, type, display_name, is_active, created_at, updated_at)
        VALUES ('p-dana', 'workspace_member', 'Dana', 1, '2026-01-01', '2026-01-01')
        """
    )
    conn.execute(
        """
        INSERT INTO inbound_events (
          id, trigger_type, sender_principal_id, trust_label,
          payload_json, processing_status, received_at
        ) VALUES ('ev-origin', 'direct_address', 'p-dana', 'internal-authenticated',
                  ?, 'done', '2026-01-01')
        """,
        (json.dumps(origin_payload),),
    )
    conn.execute(
        """
        INSERT INTO turns (id, ai_employee_id, triggering_event_id, current_status, started_at)
        VALUES ('turn1', 'agent1', 'ev-origin', 'completed', '2026-01-01')
        """
    )
    conn.commit()

    _timer(conn, scheduled_at="2020-01-01T00:00:00.000Z")
    assert fire_due_timers(conn) == 1

    event = conn.execute(
        "SELECT * FROM inbound_events WHERE trigger_type = 'timer'"
    ).fetchone()
    payload = json.loads(event["payload_json"])
    # Origin context copied — say routes back to the Slack thread.
    assert payload["connector_type"] == "slack"
    assert payload["external_channel_id"] == "C100"
    assert payload["external_thread_id"] == "1718.0001"
    assert event["sender_principal_id"] == "p-dana"
    assert "requested by Dana" in payload["message_text"]


def test_fired_timer_does_not_fire_again(conn: sqlite3.Connection) -> None:
    _timer(conn, scheduled_at="2020-01-01T00:00:00.000Z")
    assert fire_due_timers(conn) == 1
    assert fire_due_timers(conn) == 0
    count = conn.execute("SELECT COUNT(*) FROM inbound_events").fetchone()[0]
    assert count == 1


def test_find_pending_timer_near(conn: sqlite3.Connection) -> None:
    _timer(conn, scheduled_at="2026-06-10T21:06:29.000Z")
    near = find_pending_timer_near(
        conn,
        ai_employee_id="agent1",
        originating_turn_id="turn1",
        scheduled_at="2026-06-10T21:06:32.000Z",  # 3s later — duplicate
    )
    assert near is not None
    far = find_pending_timer_near(
        conn,
        ai_employee_id="agent1",
        originating_turn_id="turn1",
        scheduled_at="2026-06-10T21:08:00.000Z",  # 91s later — distinct
    )
    assert far is None
    other_turn = find_pending_timer_near(
        conn,
        ai_employee_id="agent1",
        originating_turn_id="turn2",
        scheduled_at="2026-06-10T21:06:29.000Z",
    )
    assert other_turn is None


def _schedule_ctx(conn: sqlite3.Connection) -> SimpleNamespace:
    return SimpleNamespace(
        workspace=SimpleNamespace(db_bridge=conn),
        agent=SimpleNamespace(
            agent_id="agent1",
            agent_principal_id="p1",
            display_name="Sam",
            role_title="Support",
        ),
        event=SimpleNamespace(trust_label=TrustLabel.INTERNAL_AUTHENTICATED),
        turn=SimpleNamespace(id="turn1"),
        egress=None,
        invocation_id=None,
    )


def test_reissued_schedule_self_is_deduped(conn: sqlite3.Connection) -> None:
    """Models sometimes repeat a schedule_self they already made in the same
    turn (rephrased reason, same delay) — only one timer should be created."""
    ctx = _schedule_ctx(conn)

    def schedule(reason: str) -> str:
        action = ProposedAction(
            action_type=ActionType.SCHEDULE_SELF,
            params={"delay_minutes": 0.5, "reason": reason},
        )
        return execute_action(ctx, action)  # type: ignore[arg-type]

    first = schedule("Send a reminder message to the user as requested")
    assert first.startswith("Scheduled wake-up")
    second = schedule("Remind the user as requested - they asked for a reminder")
    assert second.startswith("Already scheduled")

    count = conn.execute("SELECT COUNT(*) FROM agent_timers").fetchone()[0]
    assert count == 1


def test_guard_catches_observed_double_schedule_offsets(conn: sqlite3.Connection) -> None:
    """Regression check against the real double-reminder incidents.

    Each observed double came from one turn calling schedule_self twice across
    consecutive invocations. Both calls used the same delay, so the second
    timer's fire time is offset from the first by the inter-call gap (one LLM
    round-trip). These are the actual gaps seen in production data.
    """
    base = "2026-06-10T21:06:29.000Z"
    _timer(conn, scheduled_at=base)

    from datetime import datetime, timedelta

    base_dt = datetime.fromisoformat(base.replace("Z", "+00:00"))
    # gaps from the four logged incidents (seconds between the paired timers)
    for gap in (2.6, 6.2, 7.6, 7.6):
        second = base_dt + timedelta(seconds=gap)
        scheduled_at = second.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        near = find_pending_timer_near(
            conn,
            ai_employee_id="agent1",
            originating_turn_id="turn1",
            scheduled_at=scheduled_at,
        )
        assert near is not None, f"guard missed a {gap}s re-issue — double would slip through"

    # Failure boundary: a re-issue beyond the 20s window is NOT caught, so a
    # slower round-trip would still produce a duplicate.
    beyond = base_dt + timedelta(seconds=21)
    scheduled_at = beyond.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    assert (
        find_pending_timer_near(
            conn,
            ai_employee_id="agent1",
            originating_turn_id="turn1",
            scheduled_at=scheduled_at,
        )
        is None
    )


def test_distinct_delays_create_two_timers(conn: sqlite3.Connection) -> None:
    ctx = _schedule_ctx(conn)
    for delay in (1.0, 10.0):
        action = ProposedAction(
            action_type=ActionType.SCHEDULE_SELF,
            params={"delay_minutes": delay, "reason": "check in"},
        )
        result = execute_action(ctx, action)  # type: ignore[arg-type]
        assert result.startswith("Scheduled wake-up")
    count = conn.execute("SELECT COUNT(*) FROM agent_timers").fetchone()[0]
    assert count == 2
