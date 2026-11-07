-- 009_devwork: the Developer Worker (specs/DEVELOPER_WORKER_SPEC.html).
-- A hired developer watches Linear as its own member and runs Claude Code on
-- tickets, each in its own git worktree. Three tables:
--   dev_workers      per-developer configuration + watcher liveness
--   code_runs        one row per Claude Code run on a ticket
--   code_run_events  the run timeline (claimed, worktree ready, comments, ...)

CREATE TABLE dev_workers (
  ai_employee_id         TEXT PRIMARY KEY,
  enabled                INTEGER NOT NULL DEFAULT 0,
  linear_installation_id TEXT,
  team_id                TEXT,
  team_key               TEXT,
  viewer_id              TEXT,          -- the Linear member the worker acts as
  viewer_name            TEXT,
  owner_linear_id        TEXT,          -- hand-offs are assigned here
  owner_linear_name      TEXT,
  repo_path              TEXT,
  base_branch            TEXT NOT NULL DEFAULT 'main',
  worktree_root          TEXT,
  setup_command          TEXT,
  branch_pattern         TEXT NOT NULL DEFAULT 'claude/{key}-{slug}',
  max_concurrent         INTEGER NOT NULL DEFAULT 2,
  time_limit_min         INTEGER NOT NULL DEFAULT 60,
  idle_limit_min         INTEGER NOT NULL DEFAULT 10,
  max_turns              INTEGER NOT NULL DEFAULT 200,
  poll_seconds           INTEGER NOT NULL DEFAULT 60,
  model                  TEXT,
  permission_mode        TEXT NOT NULL DEFAULT 'allowlist',  -- allowlist | bypass
  allowed_tools          TEXT,
  rules_json             TEXT NOT NULL DEFAULT '{}',          -- toggles + skip labels
  status_map_json        TEXT NOT NULL DEFAULT '{}',          -- todo/in_progress/needs_owner/done/triage names
  queue_json             TEXT NOT NULL DEFAULT '[]',          -- eligible tickets waiting for a slot
  last_poll_at           TEXT,
  last_poll_ok_at        TEXT,
  last_poll_error        TEXT,
  created_at             TEXT NOT NULL,
  updated_at             TEXT NOT NULL
);

CREATE TABLE code_runs (
  id                 TEXT PRIMARY KEY,
  ai_employee_id     TEXT NOT NULL,
  ticket_id          TEXT NOT NULL,
  ticket_key         TEXT NOT NULL,
  ticket_title       TEXT,
  ticket_url         TEXT,
  trigger_class      TEXT NOT NULL CHECK (trigger_class IN ('assigned', 'agent_ready', 'follow_up', 'retry')),
  attempt            INTEGER NOT NULL DEFAULT 1,
  status             TEXT NOT NULL CHECK (status IN (
    'queued', 'claiming', 'preparing', 'running',
    'done', 'handed_off', 'ended_open', 'failed', 'timed_out', 'cancelled', 'dropped'
  )),
  outcome            TEXT,             -- done | needs_owner | blocked (set by the ticket tools)
  outcome_summary    TEXT,
  branch             TEXT,
  worktree_path      TEXT,
  base_sha           TEXT,
  head_sha           TEXT,
  pid                INTEGER,
  process_started_at TEXT,
  session_id         TEXT,
  heartbeat_at       TEXT,
  last_output_at     TEXT,
  log_dir            TEXT,
  exit_code          INTEGER,
  failure_reason     TEXT,
  stop_requested     INTEGER NOT NULL DEFAULT 0,
  stopped_by         TEXT,
  ticket_updated_after_stop TEXT,      -- ticket.updatedAt right after our stop writes
  input_tokens       INTEGER,
  output_tokens      INTEGER,
  cache_read_tokens  INTEGER,
  cache_write_tokens INTEGER,
  cost_usd           REAL,
  num_turns          INTEGER,
  comments_posted    INTEGER NOT NULL DEFAULT 0,
  created_at         TEXT NOT NULL,
  started_at         TEXT,
  ended_at           TEXT
);
CREATE INDEX idx_code_runs_agent ON code_runs(ai_employee_id, created_at DESC);
CREATE INDEX idx_code_runs_ticket ON code_runs(ticket_id, created_at DESC);
-- Never the same ticket twice: at most one active run per ticket.
CREATE UNIQUE INDEX idx_code_runs_one_active ON code_runs(ticket_id)
  WHERE status IN ('queued', 'claiming', 'preparing', 'running');

CREATE TABLE code_run_events (
  id          TEXT PRIMARY KEY,
  run_id      TEXT NOT NULL,
  kind        TEXT NOT NULL,
  message     TEXT NOT NULL,
  data_json   TEXT,
  occurred_at TEXT NOT NULL
);
CREATE INDEX idx_code_run_events_run ON code_run_events(run_id, occurred_at);
