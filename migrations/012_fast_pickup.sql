-- 012_fast_pickup: the new-ticket check runs every few seconds (default 5 s,
-- minimum 5 s); running-ticket checks keep their own 60 s timer in the runner.
-- Each run records how fast it started: when the ticket was last touched in
-- Linear (assignment, usually), when the runner saw it, and Claude's first output.
UPDATE dev_workers SET poll_seconds = 5 WHERE poll_seconds >= 60;
ALTER TABLE code_runs ADD COLUMN ticket_touched_at TEXT;
ALTER TABLE code_runs ADD COLUMN ticket_seen_at TEXT;
ALTER TABLE code_runs ADD COLUMN first_output_at TEXT;
