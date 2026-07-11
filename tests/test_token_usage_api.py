from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from pidgin.db import connect
from pidgin.workspace.manager import resolve_workspace_paths_by_slug
from tests.conftest import create_workspace


def _seed_invocations(pidgin_home: Path, slug: str, agent_id: str) -> None:
    """Write model_invocations straight into the workspace DB.

    The stub LLM reports no token usage, so to exercise the aggregation
    endpoints we insert invocations (and their parent turn) directly.
    """
    paths = resolve_workspace_paths_by_slug(slug, home=pidgin_home)
    conn = connect(paths.db_sqlite)
    try:
        conn.execute(
            """
            INSERT INTO turns (id, ai_employee_id, triggering_event_id,
              current_status, started_at)
            VALUES ('tt', ?, 'evt', 'completed', 'now')
            """,
            (agent_id,),
        )
        rows = [
            ("iv1", "haiku", 100, 10, 500, "2026-07-11T09:00:00.000Z", 1),
            ("iv2", "opus", 200, 20, 4000, "2026-07-12T15:00:00.000Z", 2),
        ]
        for inv_id, model_id, inp, out, cost, at, seq in rows:
            conn.execute(
                """
                INSERT INTO model_invocations (
                  id, turn_id, sequence_in_turn, provider, model_id,
                  request_messages_json, response_json,
                  input_tokens, output_tokens, cost_usd_micros, invoked_at
                ) VALUES (?, 'tt', ?, 'anthropic', ?, '[]', '{}', ?, ?, ?, ?)
                """,
                (inv_id, seq, model_id, inp, out, cost, at),
            )
        conn.commit()
    finally:
        conn.close()


def test_usage_summary_and_series(client: TestClient, pidgin_home: Path) -> None:
    slug = create_workspace(client, "Usage Co")
    handle = client.post(f"/{slug}/api/hire").json()["handle"]
    agent_id = client.get(f"/{slug}/api/agents/{handle}/inspect").json()["agent"]["id"]
    _seed_invocations(pidgin_home, slug, agent_id)

    # Workspace summary: grand sum + per-agent + per-model breakdowns.
    summary = client.get(f"/{slug}/api/usage/tokens/summary").json()
    assert summary["totals"]["input_tokens"] == 300
    assert summary["totals"]["output_tokens"] == 30
    assert summary["totals"]["total_tokens"] == 330
    assert summary["totals"]["cost_usd_micros"] == 4500
    assert summary["totals"]["invocation_count"] == 2
    assert len(summary["by_agent"]) == 1
    assert summary["by_agent"][0]["ai_employee_id"] == agent_id
    assert {m["model_id"] for m in summary["by_model"]} == {"haiku", "opus"}

    # Windowed to day 12 only.
    windowed = client.get(
        f"/{slug}/api/usage/tokens/summary",
        params={"since": "2026-07-12T00:00:00.000Z"},
    ).json()
    assert windowed["totals"]["invocation_count"] == 1
    assert windowed["totals"]["input_tokens"] == 200

    # Scoped to the agent: no by_agent breakdown, totals match.
    scoped = client.get(
        f"/{slug}/api/usage/tokens/summary", params={"agent_id": agent_id}
    ).json()
    assert scoped["by_agent"] == []
    assert scoped["totals"]["total_tokens"] == 330

    # Daily series: two buckets, input/output split.
    series = client.get(f"/{slug}/api/usage/tokens/series").json()
    assert series["granularity"] == "day"
    assert [b["bucket"] for b in series["buckets"]] == ["2026-07-11", "2026-07-12"]
    assert series["buckets"][0]["input_tokens"] == 100

    # Per-agent inspect payload carries the folded-in usage totals.
    inspect = client.get(f"/{slug}/api/agents/{handle}/inspect").json()
    assert inspect["token_usage"]["totals"]["total_tokens"] == 330


def test_usage_series_rejects_bad_granularity(client: TestClient) -> None:
    slug = create_workspace(client, "Usage Bad Co")
    resp = client.get(
        f"/{slug}/api/usage/tokens/series", params={"granularity": "week"}
    )
    assert resp.status_code == 400


def test_usage_summary_empty_workspace(client: TestClient) -> None:
    slug = create_workspace(client, "Usage Empty Co")
    summary = client.get(f"/{slug}/api/usage/tokens/summary").json()
    assert summary["totals"]["invocation_count"] == 0
    assert summary["by_agent"] == []
    assert summary["by_model"] == []
