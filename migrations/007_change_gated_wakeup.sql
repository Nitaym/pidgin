-- 007_change_gated_wakeup: a recurring wakeup runs its turn only when something
-- changed since that timer last ran; otherwise it skips (cheap, DB-only probe).
-- See specs/CHANGE_GATED_WAKEUP_SPEC.html.
--
-- Four changes:
--   1. agent_timers gains last_ran_at (per-timer baseline; the probe compares
--      against it and it advances only on a real, non-skipped run) and
--      always_run (per-timer opt-out of gating — the ungated daily floor).
--   2. inbound_events.processing_status gains 'skipped'. SQLite can't alter a
--      CHECK in place, so the table is rebuilt (FKs are app-enforced here).
--   3. turns.current_status gains 'skipped', plus skip_reason and
--      probe_snapshot_json to make a skip a first-class, auditable turn.
--   4. ai_employees gets the per-agent Advanced-config knobs: change_gating,
--      guaranteed wake times, and which change sources count.

-- 1. agent_timers: baseline + opt-out --------------------------------------
ALTER TABLE agent_timers ADD COLUMN last_ran_at TEXT;                       -- last non-skipped run; NULL until first real run
ALTER TABLE agent_timers ADD COLUMN always_run INTEGER NOT NULL DEFAULT 0;  -- 1 = never gated (the daily floor / compliance ticks)

-- 2. inbound_events: allow processing_status = 'skipped' -------------------
CREATE TABLE inbound_events_new (
  id                    TEXT PRIMARY KEY,
  trigger_type          TEXT NOT NULL CHECK (trigger_type IN (
    'direct_address', 'channel_activity', 'inbound_external',
    'timer', 'watcher', 'self_prompt',
    'peer_delegation', 'approval_response'
  )),
  target_ai_employee_id TEXT,
  sender_principal_id   TEXT,
  trust_label           TEXT NOT NULL CHECK (trust_label IN (
    'internal-authenticated', 'external-verified',
    'external-unverified', 'untrusted-content'
  )),
  resumes_turn_id       TEXT,
  parent_turn_id        TEXT,
  payload_json          TEXT NOT NULL,
  processing_status     TEXT NOT NULL DEFAULT 'pending' CHECK (processing_status IN (
    'pending', 'dispatching', 'done', 'failed', 'skipped'
  )),
  picked_up_at          TEXT,
  completed_at          TEXT,
  resulting_turn_id     TEXT,
  failure_reason        TEXT,
  received_at           TEXT NOT NULL
);
INSERT INTO inbound_events_new SELECT
  id, trigger_type, target_ai_employee_id, sender_principal_id, trust_label,
  resumes_turn_id, parent_turn_id, payload_json, processing_status,
  picked_up_at, completed_at, resulting_turn_id, failure_reason, received_at
FROM inbound_events;
DROP TABLE inbound_events;
ALTER TABLE inbound_events_new RENAME TO inbound_events;
CREATE INDEX idx_inbound_events_pending
  ON inbound_events(received_at) WHERE processing_status = 'pending';
CREATE INDEX idx_inbound_events_employee
  ON inbound_events(target_ai_employee_id, received_at DESC);

-- 3. turns: skipped status + skip audit fields ----------------------------
CREATE TABLE turns_new (
  id                  TEXT PRIMARY KEY,
  ai_employee_id      TEXT NOT NULL,
  conversation_id     TEXT,
  triggering_event_id TEXT NOT NULL,
  parent_turn_id      TEXT,
  current_status      TEXT NOT NULL DEFAULT 'running' CHECK (current_status IN (
    'running', 'suspended', 'completed', 'failed', 'refused', 'skipped'
  )),
  suspension_reason   TEXT,
  skip_reason         TEXT,               -- why a skipped turn skipped (e.g. 'nothing_changed')
  probe_snapshot_json TEXT,               -- the change-probe result that justified the skip
  started_at          TEXT NOT NULL,
  ended_at            TEXT
);
INSERT INTO turns_new (
  id, ai_employee_id, conversation_id, triggering_event_id, parent_turn_id,
  current_status, suspension_reason, started_at, ended_at
)
SELECT
  id, ai_employee_id, conversation_id, triggering_event_id, parent_turn_id,
  current_status, suspension_reason, started_at, ended_at
FROM turns;
DROP TABLE turns;
ALTER TABLE turns_new RENAME TO turns;
CREATE INDEX idx_turns_employee_started ON turns(ai_employee_id, started_at DESC);
CREATE INDEX idx_turns_active
  ON turns(current_status) WHERE current_status IN ('running', 'suspended');

-- 4. ai_employees: per-agent Advanced config ------------------------------
ALTER TABLE ai_employees ADD COLUMN change_gating_enabled INTEGER NOT NULL DEFAULT 1;  -- 0 = every recurring wakeup runs (legacy)
ALTER TABLE ai_employees ADD COLUMN guaranteed_wake_times_json TEXT;                    -- JSON list "HH:MM"; NULL = default ["09:00"]
ALTER TABLE ai_employees ADD COLUMN change_sources_json TEXT;                           -- JSON list of enabled source keys; NULL = all five
