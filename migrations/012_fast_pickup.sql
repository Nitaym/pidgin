-- 012_fast_pickup: the new-ticket check runs every 15 s by default (minimum
-- 5 s); running tickets are checked on their own 15 s timer, which also
-- forwards the owner's new comments into the running session.
-- Each run records how fast it started: when the ticket was last touched in
-- Linear (assignment, usually), when the runner saw it, and Claude's first output.
UPDATE dev_workers SET poll_seconds = 15 WHERE poll_seconds >= 60;
ALTER TABLE code_runs ADD COLUMN ticket_touched_at TEXT;
ALTER TABLE code_runs ADD COLUMN ticket_seen_at TEXT;
ALTER TABLE code_runs ADD COLUMN first_output_at TEXT;
-- Newest Linear comment time already in the run's session; newer comments by the
-- owner are forwarded into it.
ALTER TABLE code_runs ADD COLUMN comment_cursor TEXT;
