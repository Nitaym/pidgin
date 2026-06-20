-- 005_autonomy: self-running agents.
--
-- Two changes, both additive in spirit:
--   1. agent_timers gains self-anchored (no conversation) + recurring timers.
--      originating_turn_id becomes nullable; a kind discriminator and a
--      recurrence rule are added. SQLite can't relax NOT NULL in place, so the
--      table is rebuilt (nothing references it by FK).
--   2. ai_employees gets a bootstrapped_at marker so activation wakes the agent
--      exactly once.
-- See AUTONOMY_SPEC.md §3–5.

CREATE TABLE agent_timers_new (
  id                    TEXT PRIMARY KEY,
  ai_employee_id        TEXT NOT NULL,
  scheduled_at          TEXT NOT NULL,
  reason                TEXT NOT NULL,
  originating_turn_id   TEXT,                              -- NULL = self-anchored (no conversation)
  inherited_trust_label TEXT NOT NULL,
  kind                  TEXT NOT NULL DEFAULT 'oneshot'
                        CHECK (kind IN ('oneshot', 'recurring', 'bootstrap')),
  recurrence_json       TEXT,                              -- RRULE-lite, recurring only
  status                TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'fired', 'cancelled')),
  fired_at              TEXT,
  fired_event_id        TEXT,
  created_at            TEXT NOT NULL,
  updated_at            TEXT NOT NULL
);

INSERT INTO agent_timers_new (
  id, ai_employee_id, scheduled_at, reason, originating_turn_id,
  inherited_trust_label, status, fired_at, fired_event_id, created_at, updated_at
)
SELECT
  id, ai_employee_id, scheduled_at, reason, originating_turn_id,
  inherited_trust_label, status, fired_at, fired_event_id, created_at, updated_at
FROM agent_timers;

DROP TABLE agent_timers;
ALTER TABLE agent_timers_new RENAME TO agent_timers;

CREATE INDEX idx_agent_timers_pending ON agent_timers(scheduled_at) WHERE status = 'pending';
CREATE INDEX idx_agent_timers_employee ON agent_timers(ai_employee_id, status);

ALTER TABLE ai_employees ADD COLUMN bootstrapped_at TEXT;
