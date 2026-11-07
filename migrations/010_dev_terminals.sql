-- Interactive Claude Code devs the owner works with directly in Pidgin's terminals.
-- Each dev is one Claude Code session (session_id) in a folder; the live process
-- lives in the server, and the session resumes after a restart.
CREATE TABLE IF NOT EXISTS dev_terminals (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cwd TEXT NOT NULL,
    session_id TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_dev_terminals_live ON dev_terminals(archived_at, position);
