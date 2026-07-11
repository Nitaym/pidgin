from __future__ import annotations

import json
import sqlite3
from typing import Any


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def list_inbound_events(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, trigger_type, processing_status, trust_label,
               target_ai_employee_id, received_at, picked_up_at, completed_at,
               resulting_turn_id, payload_json
        FROM inbound_events
        ORDER BY received_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def list_turns(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    from pidgin.storage.sqlite.turn_store import SqliteTurnStore

    store = SqliteTurnStore(conn)
    return [turn.model_dump() for turn in store.list_turns(limit=limit)]


def get_turn(conn: sqlite3.Connection, turn_id: str) -> dict[str, Any] | None:
    from pidgin.storage.sqlite.turn_store import SqliteTurnStore

    store = SqliteTurnStore(conn)
    detail = store.get_turn_detail(turn_id)
    if detail is None:
        return None
    return {
        "turn": detail.turn.model_dump(),
        "triggering_event": (
            detail.triggering_event.model_dump() if detail.triggering_event else None
        ),
        "model_invocations": [row.model_dump() for row in detail.invocations],
        "audit": [row.model_dump() for row in detail.gate_decisions],
    }


def list_model_invocations(
    conn: sqlite3.Connection,
    limit: int = 50,
    after: str | None = None,
    ai_employee_id: str | None = None,
) -> list[dict[str, Any]]:
    """Every LLM request/response across all turns, newest first.

    `after` is an invocation id cursor (ULIDs sort by time): pass the newest id
    you have seen to fetch only invocations recorded since then — this is what
    lets the inspector tail live traffic cheaply. `ai_employee_id` scopes the
    stream to a single agent (its console).
    """
    base_sql = """
        SELECT mi.id, mi.turn_id, mi.sequence_in_turn, mi.provider, mi.model_id,
               mi.request_messages_json, mi.request_tools_json, mi.response_json,
               mi.input_tokens, mi.output_tokens, mi.cost_usd_micros,
               mi.latency_ms, mi.error_text, mi.invoked_at,
               t.ai_employee_id, t.conversation_id, t.current_status AS turn_status,
               e.trigger_type, e.payload_json AS event_payload_json,
               a.display_name AS agent_display_name, a.handle AS agent_handle
        FROM model_invocations mi
        LEFT JOIN turns t ON t.id = mi.turn_id
        LEFT JOIN inbound_events e ON e.id = t.triggering_event_id
        LEFT JOIN ai_employees a ON a.id = t.ai_employee_id
    """
    clauses: list[str] = []
    params: list[Any] = []
    if after:
        clauses.append("mi.id > ?")
        params.append(after)
    if ai_employee_id:
        clauses.append("t.ai_employee_id = ?")
        params.append(ai_employee_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        base_sql + where + " ORDER BY mi.id DESC LIMIT ?",
        (*params, limit),
    ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        item = _row_to_dict(row)
        item["request_messages"] = _loads_or(item.pop("request_messages_json"), [])
        item["request_tools"] = _loads_or(item.pop("request_tools_json"), [])
        item["response"] = _loads_or(item.pop("response_json"), None)
        payload = _loads_or(item.pop("event_payload_json"), {})
        item["source"] = (
            payload.get("connector_type", "pidgin_chat")
            if isinstance(payload, dict)
            else "pidgin_chat"
        )
        items.append(item)
    return items


def _loads_or(raw: Any, default: Any) -> Any:
    if not isinstance(raw, str) or not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def token_usage_totals(
    conn: sqlite3.Connection,
    *,
    ai_employee_id: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Summed token usage across model invocations.

    Every LLM call is a permanent row in ``model_invocations`` carrying its
    input/output tokens and estimated cost, joined to its agent through
    ``turns``. Pass ``ai_employee_id`` to scope to one agent (its lifetime
    spend); omit it for the whole workspace. ``since`` is an ISO timestamp lower
    bound on ``invoked_at`` for a windowed total (e.g. today or the last 30
    days). Skipped turns run no invocations, so they contribute nothing.
    """
    where, params = _usage_where(ai_employee_id=ai_employee_id, since=since)
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(mi.input_tokens), 0)   AS input_tokens,
               COALESCE(SUM(mi.output_tokens), 0)  AS output_tokens,
               COALESCE(SUM(mi.cost_usd_micros), 0) AS cost_usd_micros,
               COUNT(*)                            AS invocation_count
        FROM model_invocations mi
        JOIN turns t ON t.id = mi.turn_id
        {where}
        """,
        params,
    ).fetchone()
    return _usage_totals_row(row)


def token_usage_by_agent(
    conn: sqlite3.Connection,
    *,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Token usage grouped by agent, biggest spender first — the 'per agent' view."""
    where, params = _usage_where(since=since)
    rows = conn.execute(
        f"""
        SELECT t.ai_employee_id,
               a.handle       AS agent_handle,
               a.display_name AS agent_display_name,
               COALESCE(SUM(mi.input_tokens), 0)   AS input_tokens,
               COALESCE(SUM(mi.output_tokens), 0)  AS output_tokens,
               COALESCE(SUM(mi.cost_usd_micros), 0) AS cost_usd_micros,
               COUNT(*)                            AS invocation_count
        FROM model_invocations mi
        JOIN turns t ON t.id = mi.turn_id
        LEFT JOIN ai_employees a ON a.id = t.ai_employee_id
        {where}
        GROUP BY t.ai_employee_id
        ORDER BY (COALESCE(SUM(mi.input_tokens), 0)
                  + COALESCE(SUM(mi.output_tokens), 0)) DESC
        """,
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = _usage_totals_row(row)
        item["ai_employee_id"] = row["ai_employee_id"]
        item["agent_handle"] = row["agent_handle"]
        item["agent_display_name"] = row["agent_display_name"]
        out.append(item)
    return out


def token_usage_by_model(
    conn: sqlite3.Connection,
    *,
    ai_employee_id: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Token usage grouped by model id, biggest first."""
    where, params = _usage_where(ai_employee_id=ai_employee_id, since=since)
    rows = conn.execute(
        f"""
        SELECT mi.model_id, mi.provider,
               COALESCE(SUM(mi.input_tokens), 0)   AS input_tokens,
               COALESCE(SUM(mi.output_tokens), 0)  AS output_tokens,
               COALESCE(SUM(mi.cost_usd_micros), 0) AS cost_usd_micros,
               COUNT(*)                            AS invocation_count
        FROM model_invocations mi
        JOIN turns t ON t.id = mi.turn_id
        {where}
        GROUP BY mi.model_id, mi.provider
        ORDER BY (COALESCE(SUM(mi.input_tokens), 0)
                  + COALESCE(SUM(mi.output_tokens), 0)) DESC
        """,
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = _usage_totals_row(row)
        item["model_id"] = row["model_id"]
        item["provider"] = row["provider"]
        out.append(item)
    return out


def token_usage_series(
    conn: sqlite3.Connection,
    *,
    granularity: str = "day",
    start: str | None = None,
    end: str | None = None,
    ai_employee_id: str | None = None,
) -> list[dict[str, Any]]:
    """Token usage bucketed over time — the usage history.

    ``invoked_at`` is a UTC ISO timestamp, so the day bucket is its first 10
    chars ("2026-07-12") and the hour bucket its first 13 ("2026-07-12T14");
    buckets are therefore UTC. Use ``granularity="day"`` for the all-time trend
    and ``"hour"`` (with a bounded ``start``/``end``) to drill into a day. Each
    bucket keeps input and output split apart. ``ai_employee_id`` scopes to one
    agent; omit it to chart all agents combined.
    """
    bucket_len = 13 if granularity == "hour" else 10
    where, where_params = _usage_where(
        ai_employee_id=ai_employee_id, since=start, until=end
    )
    rows = conn.execute(
        f"""
        SELECT substr(mi.invoked_at, 1, ?) AS bucket,
               COALESCE(SUM(mi.input_tokens), 0)   AS input_tokens,
               COALESCE(SUM(mi.output_tokens), 0)  AS output_tokens,
               COALESCE(SUM(mi.cost_usd_micros), 0) AS cost_usd_micros,
               COUNT(*)                            AS invocation_count
        FROM model_invocations mi
        JOIN turns t ON t.id = mi.turn_id
        {where}
        GROUP BY bucket
        ORDER BY bucket ASC
        """,
        (bucket_len, *where_params),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = _usage_totals_row(row)
        item["bucket"] = row["bucket"]
        out.append(item)
    return out


def _usage_where(
    *,
    ai_employee_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if ai_employee_id:
        clauses.append("t.ai_employee_id = ?")
        params.append(ai_employee_id)
    if since:
        clauses.append("mi.invoked_at >= ?")
        params.append(since)
    if until:
        clauses.append("mi.invoked_at < ?")
        params.append(until)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def _usage_totals_row(row: sqlite3.Row) -> dict[str, Any]:
    input_tokens = int(row["input_tokens"])
    output_tokens = int(row["output_tokens"])
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost_usd_micros": int(row["cost_usd_micros"]),
        "invocation_count": int(row["invocation_count"]),
    }


def agent_inspect(conn: sqlite3.Connection, handle: str) -> dict[str, Any] | None:
    """Everything worth knowing to inspect a single agent, for the dashboard.

    Bundles the agent's identity + activation state, the tools it can use, its
    open task backlog, its pending timers (its 'calendar', incl. the 30-min work
    heartbeat), what it's doing right now (its latest turn), recent turns and
    actions, and any approvals waiting on the owner. Read-only.
    """
    from pidgin.db.employees import get_agent_by_handle
    from pidgin.db.tasks import list_open_tasks
    from pidgin.llm.tools import tools_for_profile
    from pidgin.storage.sqlite.turn_store import SqliteTurnStore

    agent_row = get_agent_by_handle(conn, handle)
    if agent_row is None:
        return None

    store = SqliteTurnStore(conn)
    ctx = store.load_agent_context(agent_row["id"])

    tools = [
        {"name": t.name, "description": t.description}
        for t in tools_for_profile(ctx.permission_profile)
    ]
    tasks = list_open_tasks(conn, owner_principal_id=ctx.agent_principal_id)

    timer_rows = conn.execute(
        """
        SELECT id, scheduled_at, reason, kind, recurrence_json
        FROM agent_timers
        WHERE ai_employee_id = ? AND status = 'pending'
        ORDER BY scheduled_at ASC
        LIMIT 50
        """,
        (agent_row["id"],),
    ).fetchall()
    timers = []
    for row in timer_rows:
        timer = _row_to_dict(row)
        timer["recurrence"] = _loads_or(timer.pop("recurrence_json"), None)
        timers.append(timer)

    # A high-frequency poller can skip many times a day, so pull a wider window
    # than the real-turn count would need; the dashboard collapses runs of skips.
    turn_rows = conn.execute(
        """
        SELECT t.id, t.current_status, t.started_at, t.ended_at, t.skip_reason,
               t.probe_snapshot_json, e.trigger_type, e.payload_json AS event_payload_json
        FROM turns t
        LEFT JOIN inbound_events e ON e.id = t.triggering_event_id
        WHERE t.ai_employee_id = ?
        ORDER BY t.started_at DESC
        LIMIT 60
        """,
        (agent_row["id"],),
    ).fetchall()
    turns = []
    for row in turn_rows:
        turn = _row_to_dict(row)
        if turn.get("current_status") == "skipped":
            turn["probe_snapshot"] = _loads_or(turn.get("probe_snapshot_json"), None)
            payload = _loads_or(turn.pop("event_payload_json", None), {}) or {}
            turn["timer_id"] = payload.get("timer_id")
            turn["timer_reason"] = payload.get("timer_reason")
        else:
            turn.pop("event_payload_json", None)
        turn.pop("probe_snapshot_json", None)
        turns.append(turn)
    # "What it's doing now" — the latest real turn, flagged live when still open.
    # A skipped turn isn't activity, so it never counts as the current turn.
    real_turns = [t for t in turns if t["current_status"] != "skipped"]
    current_turn = real_turns[0] if real_turns else None
    is_working = bool(current_turn and current_turn["current_status"] in ("running", "suspended"))

    approvals = [
        _row_to_dict(row)
        for row in conn.execute(
            """
            SELECT id, proposed_action, current_status, created_at
            FROM pending_approvals
            WHERE ai_employee_id = ? AND current_status = 'open'
            ORDER BY created_at DESC
            """,
            (agent_row["id"],),
        ).fetchall()
    ]

    from pidgin.db.agent_config import read_change_gating_config

    return {
        "agent": {
            "id": agent_row["id"],
            "handle": agent_row["handle"],
            "display_name": agent_row["display_name"],
            "role_title": agent_row["role_title"],
            "current_status": agent_row["current_status"],
            "created_at": agent_row["created_at"],
            "bootstrapped_at": agent_row["bootstrapped_at"]
            if "bootstrapped_at" in agent_row.keys()
            else None,
        },
        "change_gating": read_change_gating_config(conn, agent_row["id"]),
        "token_usage": {
            "totals": token_usage_totals(conn, ai_employee_id=agent_row["id"]),
            "by_model": token_usage_by_model(conn, ai_employee_id=agent_row["id"]),
        },
        "is_working": is_working,
        "current_turn": current_turn,
        "tools": tools,
        "tasks": tasks,
        "timers": timers,
        "recent_turns": turns,
        "recent_actions": list_audit_log(conn, limit=25, ai_employee_id=agent_row["id"]),
        "open_approvals": approvals,
    }


def list_audit_log(
    conn: sqlite3.Connection,
    limit: int = 100,
    ai_employee_id: str | None = None,
) -> list[dict[str, Any]]:
    """Every gate decision, newest first — the agent action log.

    Pass `ai_employee_id` to get the complete action trail for one agent: every
    action it proposed, the gate's decision (executed / staged / refused), and
    the params. Backed by idx_action_log_employee_time.
    """
    base_sql = """
        SELECT id, turn_id, virtual_actor_ai_employee_id, virtual_actor_display_name,
               requester_display_name, action_type, policy_decision, outcome,
               trust_label, occurred_at, action_params_json
        FROM agent_action_log
    """
    if ai_employee_id:
        rows = conn.execute(
            base_sql
            + " WHERE virtual_actor_ai_employee_id = ? ORDER BY occurred_at DESC LIMIT ?",
            (ai_employee_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            base_sql + " ORDER BY occurred_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    items = [_row_to_dict(row) for row in rows]
    for item in items:
        raw = item.get("action_params_json")
        if isinstance(raw, str):
            try:
                item["action_params"] = json.loads(raw)
            except json.JSONDecodeError:
                item["action_params"] = raw
    return items
