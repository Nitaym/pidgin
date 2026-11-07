-- Devs can work in reusable "dev slots": git worktrees outside Dropbox
-- (e.g. D:\Work\apps\actual_gameplay\build_slots\slot-N), shared with the repo's
-- own ticket runner, which honours the same .agent\lock.json.
ALTER TABLE dev_terminals ADD COLUMN slot TEXT;
CREATE TABLE IF NOT EXISTS dev_terminal_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
