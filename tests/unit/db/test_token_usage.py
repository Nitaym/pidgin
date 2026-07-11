from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pidgin.db import apply_migrations, connect
from pidgin.db.diagnostics import (
    token_usage_by_agent,
    token_usage_by_model,
    token_usage_series,
    token_usage_totals,
)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db = connect(tmp_path / "db.sqlite")
    apply_migrations(db)
    return db


def _agent(conn: sqlite3.Connection, agent_id: str, handle: str) -> None:
    conn.execute(
        """
        INSERT INTO ai_employees (
          id, display_name, role_title, handle, recipe_snapshot_id,
          human_owner_principal_id, current_status, created_at, updated_at
        ) VALUES (?, ?, 'Support', ?, 'rs', 'owner', 'active', 'now', 'now')
        """,
        (agent_id, handle.title(), handle),
    )
    conn.commit()


def _turn(conn: sqlite3.Connection, turn_id: str, agent_id: str) -> None:
    conn.execute(
        """
        INSERT INTO turns (id, ai_employee_id, triggering_event_id,
          current_status, started_at)
        VALUES (?, ?, 'evt', 'completed', 'now')
        """,
        (turn_id, agent_id),
    )
    conn.commit()


def _invocation(
    conn: sqlite3.Connection,
    inv_id: str,
    turn_id: str,
    *,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cost: int,
    invoked_at: str,
    seq: int = 1,
) -> None:
    conn.execute(
        """
        INSERT INTO model_invocations (
          id, turn_id, sequence_in_turn, provider, model_id,
          request_messages_json, response_json,
          input_tokens, output_tokens, cost_usd_micros, invoked_at
        ) VALUES (?, ?, ?, 'anthropic', ?, '[]', '{}', ?, ?, ?, ?)
        """,
        (inv_id, turn_id, seq, model_id, input_tokens, output_tokens, cost, invoked_at),
    )
    conn.commit()


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> sqlite3.Connection:
    # Two agents, two models, invocations across two days.
    _agent(conn, "a1", "sam")
    _agent(conn, "a2", "kai")
    _turn(conn, "t1", "a1")
    _turn(conn, "t2", "a2")
    # a1: day 11 two calls (haiku + opus), day 12 one call (haiku)
    _invocation(conn, "i1", "t1", model_id="haiku", input_tokens=100,
                output_tokens=10, cost=500, invoked_at="2026-07-11T09:00:00.000Z", seq=1)
    _invocation(conn, "i2", "t1", model_id="opus", input_tokens=200,
                output_tokens=20, cost=4000, invoked_at="2026-07-11T15:30:00.000Z", seq=2)
    _invocation(conn, "i3", "t1", model_id="haiku", input_tokens=50,
                output_tokens=5, cost=250, invoked_at="2026-07-12T10:00:00.000Z", seq=3)
    # a2: one call on day 12
    _invocation(conn, "i4", "t2", model_id="haiku", input_tokens=1000,
                output_tokens=100, cost=5000, invoked_at="2026-07-12T11:00:00.000Z", seq=1)
    return conn


def test_totals_whole_workspace(seeded: sqlite3.Connection) -> None:
    t = token_usage_totals(seeded)
    assert t["input_tokens"] == 100 + 200 + 50 + 1000
    assert t["output_tokens"] == 10 + 20 + 5 + 100
    assert t["total_tokens"] == t["input_tokens"] + t["output_tokens"]
    assert t["cost_usd_micros"] == 500 + 4000 + 250 + 5000
    assert t["invocation_count"] == 4


def test_totals_scoped_to_agent(seeded: sqlite3.Connection) -> None:
    t = token_usage_totals(seeded, ai_employee_id="a1")
    assert t["input_tokens"] == 350
    assert t["output_tokens"] == 35
    assert t["invocation_count"] == 3


def test_totals_windowed_since(seeded: sqlite3.Connection) -> None:
    # Only the two day-12 calls fall on/after this bound.
    t = token_usage_totals(seeded, since="2026-07-12T00:00:00.000Z")
    assert t["invocation_count"] == 2
    assert t["input_tokens"] == 50 + 1000


def test_totals_empty(conn: sqlite3.Connection) -> None:
    t = token_usage_totals(conn)
    assert t == {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd_micros": 0,
        "invocation_count": 0,
    }


def test_by_agent_sorted_by_usage(seeded: sqlite3.Connection) -> None:
    rows = token_usage_by_agent(seeded)
    assert [r["ai_employee_id"] for r in rows] == ["a2", "a1"]  # a2 (1100) > a1 (385)
    assert rows[0]["agent_handle"] == "kai"
    assert rows[1]["input_tokens"] == 350


def test_by_model_scoped(seeded: sqlite3.Connection) -> None:
    rows = token_usage_by_model(seeded, ai_employee_id="a1")
    by_model = {r["model_id"]: r for r in rows}
    assert set(by_model) == {"haiku", "opus"}
    assert by_model["haiku"]["input_tokens"] == 150  # 100 + 50
    assert by_model["opus"]["input_tokens"] == 200


def test_series_daily_buckets(seeded: sqlite3.Connection) -> None:
    buckets = token_usage_series(seeded, granularity="day")
    assert [b["bucket"] for b in buckets] == ["2026-07-11", "2026-07-12"]
    assert buckets[0]["input_tokens"] == 300  # 100 + 200
    assert buckets[0]["output_tokens"] == 30
    assert buckets[1]["input_tokens"] == 1050  # 50 + 1000


def test_series_hourly_drilldown(seeded: sqlite3.Connection) -> None:
    buckets = token_usage_series(
        seeded,
        granularity="hour",
        start="2026-07-11T00:00:00.000Z",
        end="2026-07-12T00:00:00.000Z",
    )
    assert [b["bucket"] for b in buckets] == ["2026-07-11T09", "2026-07-11T15"]
    assert buckets[0]["input_tokens"] == 100
    assert buckets[1]["input_tokens"] == 200


def test_series_scoped_to_agent(seeded: sqlite3.Connection) -> None:
    buckets = token_usage_series(seeded, granularity="day", ai_employee_id="a2")
    assert [b["bucket"] for b in buckets] == ["2026-07-12"]
    assert buckets[0]["input_tokens"] == 1000
