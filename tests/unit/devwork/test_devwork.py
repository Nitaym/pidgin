from __future__ import annotations

import io
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from pidgin.db import apply_migrations, connect
from pidgin.devwork import store, ticket_mcp
from pidgin.devwork.linear_api import Issue
from pidgin.devwork.prompt import build_resume_prompt
from pidgin.devwork.runner import DevRunner, branch_for, resumable_session


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db = connect(tmp_path / "db.sqlite")
    apply_migrations(db)
    db.execute(
        """INSERT INTO ai_employees (id, display_name, role_title, handle, recipe_snapshot_id,
             human_owner_principal_id, current_status, created_at, updated_at)
           VALUES ('dev1', 'Claude', 'Developer', 'claude', 'rs', 'owner', 'active', 'now', 'now')"""
    )
    db.commit()
    return db


def _issue(
    key: str,
    *,
    assignee: str | None,
    labels: tuple[str, ...] = (),
    priority: int = 0,
    created: str = "2026-01-01",
    blocked: bool = False,
) -> Issue:
    return Issue(
        id=f"id-{key}",
        key=key,
        title=f"Title {key}",
        url="u",
        branch_name=f"nitay/{key.lower()}-fix-it",
        priority=priority,
        created_at=created,
        updated_at="t1",
        state_id="todo",
        state_name="Todo",
        state_type="unstarted",
        assignee_id=assignee,
        assignee_name=None,
        team_id="team",
        label_ids={lbl: f"l-{lbl}" for lbl in labels},
        blocked=blocked,
    )


def test_one_active_run_per_ticket(conn: sqlite3.Connection) -> None:
    first = store.create_run(
        conn,
        ai_employee_id="dev1",
        ticket_id="T1",
        ticket_key="ACG-1",
        ticket_title="t",
        ticket_url="u",
        trigger_class="assigned",
    )
    assert first is not None
    again = store.create_run(
        conn,
        ai_employee_id="dev1",
        ticket_id="T1",
        ticket_key="ACG-1",
        ticket_title="t",
        ticket_url="u",
        trigger_class="assigned",
    )
    assert again is None
    store.update_run(conn, first, status="failed")
    retry = store.create_run(
        conn,
        ai_employee_id="dev1",
        ticket_id="T1",
        ticket_key="ACG-1",
        ticket_title="t",
        ticket_url="u",
        trigger_class="retry",
    )
    assert retry is not None
    assert store.get_run(conn, retry)["attempt"] == 2  # type: ignore[index]


def test_branch_names() -> None:
    w = {"branch_pattern": "claude/{key}-{slug}"}
    assert (
        branch_for(w, "ACG-131", "nitay/acg-131-the-boss-falls-slower", "x")
        == "claude/acg-131-the-boss-falls-slower"
    )
    assert branch_for(w, "ACG-7", "", "Pour Sort: level 12!") == "claude/acg-7-pour-sort-level-12"


def test_queue_rules(conn: sqlite3.Connection) -> None:
    worker = store.ensure_worker(conn, "dev1", "claude")
    worker["viewer_id"] = "me"
    issues = [
        _issue("ACG-1", assignee=None, labels=("agent-ready",)),
        _issue("ACG-2", assignee="me", priority=3),
        _issue("ACG-3", assignee="me", priority=1),
        _issue("ACG-4", assignee="someone-else"),  # Todo, not for us
        _issue("ACG-5", assignee=None),  # Todo alone: never
        _issue("ACG-6", assignee="me", labels=("runner-failed",)),
        _issue("ACG-7", assignee="me", blocked=True),
        _issue("ACG-8", assignee="me", labels=("owner-only",)),
    ]
    queue = DevRunner(None)._queue_from(conn, worker, issues)
    keys = [q["key"] for q in queue]
    assert "ACG-4" not in keys and "ACG-5" not in keys
    assert keys[:2] == ["ACG-3", "ACG-2"]  # assigned first, urgent before medium
    by_key = {q["key"]: q for q in queue}
    assert by_key["ACG-1"]["reason"] == "Waits until no assigned ticket is waiting"
    assert by_key["ACG-6"]["reason"].startswith("Skipped")
    assert by_key["ACG-7"]["reason"].startswith("Skipped: blocked")
    assert by_key["ACG-8"]["reason"].startswith("Skipped")


def test_queue_skips_ticket_with_active_run(conn: sqlite3.Connection) -> None:
    worker = store.ensure_worker(conn, "dev1", "claude")
    worker["viewer_id"] = "me"
    store.create_run(
        conn,
        ai_employee_id="dev1",
        ticket_id="id-ACG-2",
        ticket_key="ACG-2",
        ticket_title="t",
        ticket_url="u",
        trigger_class="assigned",
    )
    queue = DevRunner(None)._queue_from(conn, worker, [_issue("ACG-2", assignee="me")])
    assert queue == []


class _FakeTools:
    def call(self, name: str, args: dict) -> str:
        return f"called {name}"


def test_mcp_handshake(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "comment", "arguments": {"body": "hi"}},
        },
    ]
    monkeypatch.setattr(
        sys, "stdin", io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    )
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    ticket_mcp.serve(_FakeTools())  # type: ignore[arg-type]
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert replies[0]["result"]["serverInfo"]["name"] == "pidgin-ticket"
    assert {t["name"] for t in replies[1]["result"]["tools"]} >= {
        "comment",
        "done",
        "needs_owner",
        "blocked",
    }
    assert replies[2]["result"]["content"][0]["text"] == "called comment"


def test_resume_only_same_worktree_with_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    wt = str(tmp_path / "wt" / "ACG-1")
    last = {"attempt": 1, "status": "handed_off", "session_id": "s1", "worktree_path": wt}
    assert resumable_session([last], wt) is None  # no transcript on disk
    proj = tmp_path / "cfg" / "projects" / "some-dir"
    proj.mkdir(parents=True)
    (proj / "s1.jsonl").write_text("{}", encoding="utf-8")
    assert resumable_session([last], wt) == (last, "s1")
    assert resumable_session([last], str(tmp_path / "other")) is None
    assert resumable_session([{**last, "session_id": None}], wt) is None
    assert resumable_session([], wt) is None


def test_resume_prompt_has_only_new_comments() -> None:
    issue = {
        "identifier": "ACG-1",
        "title": "Fix it",
        "state": {"name": "Todo"},
        "comments": {
            "nodes": [
                {"createdAt": "2026-11-01T10:00", "body": "stale note", "user": {"id": "own"}},
                {"createdAt": "2026-11-02T10:00", "body": "mine", "user": {"id": "bot"}},
                {"createdAt": "2026-11-03T10:00", "body": "go with B", "user": {"id": "own"}},
            ]
        },
    }
    text = build_resume_prompt(
        issue,
        worker={"owner_linear_id": "own", "viewer_id": "bot"},
        run={"attempt": 2},
        previous={"status": "handed_off", "ended_at": "2026-11-02T00:00", "attempt": 1},
    )
    assert "go with B" in text and "stale note" not in text and "mine" not in text


def test_transcript_reads_like_a_terminal(tmp_path: Path) -> None:
    from pidgin.devwork.transcript import transcript

    wt = str(tmp_path / "wt")
    (tmp_path / "prompt.md").write_text("# Ticket ACG-9: Fix it\n...", encoding="utf-8")
    events = [
        {"type": "system", "subtype": "init", "model": "m", "session_id": "abcdef123", "cwd": wt},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Looking at it."},
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": wt + "/src/a.ts"}},
            {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "npm test"}},
            {"type": "tool_use", "id": "t3", "name": "TodoWrite", "input": {"todos": [
                {"content": "fix", "status": "in_progress"}]}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "a\nb\nc"},
            {"type": "tool_result", "tool_use_id": "t2", "is_error": True,
             "content": [{"type": "text", "text": "\n".join(f"l{i}" for i in range(9))}]},
        ]}},
    ]
    stream = tmp_path / "stream.jsonl"
    stream.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    t = transcript(str(tmp_path), wt)
    assert t["prompt"] == "Ticket ACG-9: Fix it"
    kinds = [e["k"] for e in t["entries"]]
    assert kinds == ["init", "say", "tool", "tool", "todos"]
    read, bash = t["entries"][2], t["entries"][3]
    assert (read["name"], read["arg"], read["out"]) == ("Read", "src/a.ts", ["Read 3 lines"])
    assert bash["status"] == "error" and len(bash["out"]) == 4 and bash["more"] == 5

    # Incremental: a half-written line waits; the finished result is appended.
    with open(stream, "a", encoding="utf-8") as fh:
        fh.write('{"type": "result", "subtype": "success", "num_turns": 3')
    assert transcript(str(tmp_path), wt)["total"] == 5
    with open(stream, "a", encoding="utf-8") as fh:
        fh.write("}\n")
    last = transcript(str(tmp_path), wt)["entries"][-1]
    assert last["k"] == "end" and last["ok"] is True


def test_dev_slots_take_create_and_lock(tmp_path: Path) -> None:
    import os
    import subprocess

    from pidgin.devwork import slots as dev_slots

    def git(cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp_path / "repo"
    git(tmp_path, "clone", "-q", str(origin), str(repo))
    (repo / "a.txt").write_text("a", encoding="utf-8")
    (repo / "research").mkdir()
    (repo / "research" / "big.txt").write_text("x", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    git(repo, "push", "-q", "origin", "main")

    settings = {**dev_slots.DEFAULTS, "slots_dir": str(tmp_path / "slots")}
    name, path = dev_slots.take_slot(settings, str(repo), [])
    assert name == "slot-1" and (Path(path) / "a.txt").exists()
    assert not (Path(path) / "research").exists()  # sparse: research left out

    # A dev in slot-1 means the next dev gets a new slot-2.
    devs = [{"name": "Dev 1", "slot": "slot-1"}]
    assert dev_slots.take_slot(settings, str(repo), devs)[0] == "slot-2"

    # A live lock (the runner's or another process's) keeps a slot taken.
    dev_slots.write_lock(path, pid=os.getpid(), dev_name="x", branch=None)
    states = {s["name"]: s["state"] for s in dev_slots.list_slots(settings, [])}
    assert states == {"slot-1": "busy", "slot-2": "free"}
    dev_slots.clear_lock(path, 999999)  # not ours: stays
    assert dev_slots.read_lock(Path(path)) is not None
    dev_slots.clear_lock(path, os.getpid())
    assert dev_slots.read_lock(Path(path)) is None


# -- fast pickup: 5 s new-ticket checks, 60 s running checks, rate budget ---------


def test_new_worker_polls_every_5_seconds(conn: sqlite3.Connection) -> None:
    worker = store.ensure_worker(conn, "dev1", "claude")
    assert worker["poll_seconds"] == 5
    assert DevRunner._base_interval({"poll_seconds": 1}) == 5  # minimum 5 s


def test_rate_headers_parsed() -> None:
    from pidgin.devwork.linear_api import parse_rate_headers

    rate = parse_rate_headers(
        {
            "x-ratelimit-requests-limit": "2500",
            "x-ratelimit-requests-remaining": "2400",
            "x-ratelimit-requests-reset": "1794060000000",
            "x-ratelimit-complexity-limit": "3000000",
            "x-ratelimit-complexity-remaining": "2999000",
            "x-complexity": "36",
        }
    )
    assert rate is not None
    assert (rate.requests_remaining, rate.requests_limit, rate.last_complexity) == (2400, 2500, 36)
    assert rate.requests_reset == 1794060000.0  # milliseconds -> seconds
    assert parse_rate_headers({}) is None


def test_poll_plan_backs_off_when_requests_run_low() -> None:
    from pidgin.devwork.linear_api import RateInfo
    from pidgin.devwork.runner import poll_plan

    now = 1_000_000.0
    plenty = RateInfo(requests_limit=2500, requests_remaining=2000, requests_reset=now + 1800)
    assert poll_plan(5, plenty, now) == (5, None)
    assert poll_plan(5, None, now) == (5, None)

    # 500 left (20%), 250 kept in reserve: 250 polls over 30 min = one every 7.2 s.
    low = RateInfo(requests_limit=2500, requests_remaining=500, requests_reset=now + 1800)
    every, note = poll_plan(5, low, now)
    assert every == pytest.approx(7.2)
    assert note and "500 of 2,500 Linear requests" in note

    # Inside the reserve: wait for the reset.
    empty = RateInfo(requests_limit=2500, requests_remaining=100, requests_reset=now + 900)
    assert poll_plan(5, empty, now)[0] == pytest.approx(900)

    # Complexity runs low too, measured in polls of this cost.
    cx = RateInfo(
        requests_limit=2500,
        requests_remaining=2400,
        complexity_limit=3_000_000,
        complexity_remaining=400_000,
        complexity_reset=now + 3600,
    )
    every, note = poll_plan(5, cx, now, poll_cost=20_000)
    assert every == pytest.approx(3600 * 20_000 / 100_000)
    assert note and "complexity" in note


def test_todo_query_is_two_small_filtered_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    from pidgin.devwork.linear_api import LinearClient

    seen: dict = {}

    def fake_gql(self, query, variables=None):  # noqa: ANN001
        seen["query"], seen["vars"] = query, variables
        node = {"id": "i1", "identifier": "ACG-1", "assignee": {"id": "me"}}
        return {"mine": {"nodes": [node]}, "ready": {"nodes": []}}

    monkeypatch.setattr(LinearClient, "gql", fake_gql)
    issues = LinearClient("k").todo_issues("team", "todo", viewer_id="me", ready_label="agent-ready")
    assert [i.key for i in issues] == ["ACG-1"]
    assert "mine: issues(first: $first" in seen["query"] and "ready: issues" in seen["query"]
    assert "description" not in seen["query"] and "comments" not in seen["query"]
    assert seen["vars"]["first"] <= 25
    assert seen["vars"]["mine"]["assignee"] == {"id": {"eq": "me"}}
    assert seen["vars"]["ready"]["assignee"] == {"null": True}


class _FakeLinear:
    def __init__(self, todo: list[Issue], brief: list[Issue] | None = None) -> None:
        self.todo, self.brief = todo, brief or []
        self.calls: list[str] = []
        self.rate = None

    def team_meta(self, team_id: str) -> dict:
        self.calls.append("team_meta")
        return {"states": [{"id": "todo", "name": "Todo"}, {"id": "prog", "name": "In Progress"}]}

    def todo_issues(self, *a, **k) -> list[Issue]:  # noqa: ANN002, ANN003
        self.calls.append("todo")
        return self.todo

    def issues_brief(self, ids: list[str]) -> list[Issue]:
        self.calls.append("brief")
        return self.brief


def _ready_worker(conn: sqlite3.Connection) -> None:
    store.ensure_worker(conn, "dev1", "claude")
    store.update_worker(
        conn,
        "dev1",
        {
            "enabled": 1,
            "linear_installation_id": "li",
            "team_id": "team",
            "repo_path": "C:/nowhere",
            "viewer_id": "me",
            "max_concurrent": 2,
        },
    )


def test_tick_polls_every_5_s_and_starts_in_the_same_pass(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pidgin.devwork import runner as runner_mod

    _ready_worker(conn)
    fake = _FakeLinear([_issue("ACG-2", assignee="me")])
    monkeypatch.setattr(runner_mod, "linear_for_worker", lambda c, w: fake)
    r = DevRunner(None)
    monkeypatch.setattr(r, "_uses_slots", lambda c, w: False)
    started: list[str] = []
    monkeypatch.setattr(r, "_start_prepare", lambda run_id, recovering: started.append(run_id))

    r.tick(conn)
    assert fake.calls.count("todo") == 1
    assert len(started) == 1  # claimed and started in the pass that saw it
    run = store.get_run(conn, started[0])
    assert run and run["ticket_key"] == "ACG-2" and run["ticket_seen_at"]
    assert run["ticket_touched_at"] == "t1"

    r.tick(conn)  # under 5 s later: no new request
    assert fake.calls.count("todo") == 1
    store.update_worker(conn, "dev1", {"last_poll_at": "2000-01-01T00:00:00.000Z"})
    r.tick(conn)
    assert fake.calls.count("todo") == 2


def test_running_tickets_checked_on_their_own_timer(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pidgin.devwork import runner as runner_mod

    _ready_worker(conn)
    run_id = store.create_run(
        conn,
        ai_employee_id="dev1",
        ticket_id="id-ACG-3",
        ticket_key="ACG-3",
        ticket_title="t",
        ticket_url="u",
        trigger_class="assigned",
    )
    assert run_id is not None
    store.update_run(conn, run_id, status="running")
    fake = _FakeLinear([], brief=[_issue("ACG-3", assignee="someone-else")])
    monkeypatch.setattr(runner_mod, "linear_for_worker", lambda c, w: fake)
    r = DevRunner(None)
    worker = store.get_worker(conn, "dev1")
    assert worker is not None
    assert r._check_due(worker)
    r._check_running(conn, worker)
    assert fake.calls == ["brief"]  # one request for every running ticket
    run = store.get_run(conn, run_id)
    assert run and run["stop_requested"] == 1 and run["stopped_by"] == "Linear"
    assert not r._check_due(worker)  # next one in 60 s


def test_runs_take_a_clean_slot_and_switch_branch(tmp_path: Path) -> None:
    import os
    import subprocess

    from pidgin.devwork import slots as dev_slots

    def git(cwd: Path, *args: str) -> str:
        done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
        return done.stdout

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")

    settings = {**dev_slots.DEFAULTS, "slots_dir": str(tmp_path / "slots"), "slots_repo": str(repo)}
    assert dev_slots.belongs_to(settings, str(repo))  # no slots yet, configured repo
    name, path, created = dev_slots.take_run_slot(
        settings, str(repo), [], ticket="ACG-9", branch="claude/acg-9-x"
    )
    assert (name, created) == ("slot-1", True)
    assert dev_slots.belongs_to(settings, str(repo))
    lock = dev_slots.read_lock(Path(path))
    assert lock and lock["mode"] == "pidgin-run" and lock["ticket"] == "ACG-9"
    assert lock["pid"] == os.getpid()
    dev_slots.switch_to_branch(path, "claude/acg-9-x", "main")
    assert git(Path(path), "branch", "--show-current").strip() == "claude/acg-9-x"

    one = {**settings, "max_slots": "1"}
    assert dev_slots.free_run_slots(one, []) == 0  # taken
    dev_slots.clear_lock(path, None)
    (Path(path) / "a.txt").write_text("changed", encoding="utf-8")
    assert dev_slots.free_run_slots(one, []) == 0  # free but has uncommitted work
    with pytest.raises(dev_slots.NoFreeSlot):
        dev_slots.take_run_slot(one, str(repo), [], ticket="ACG-10", branch="b")
    git(Path(path), "checkout", "--", "a.txt")
    assert dev_slots.free_run_slots(one, []) == 1
    # The branch already exists: a later round checks it out as it is.
    git(Path(path), "switch", "-q", "--detach", "main")
    dev_slots.switch_to_branch(path, "claude/acg-9-x", "main")
    assert git(Path(path), "branch", "--show-current").strip() == "claude/acg-9-x"
