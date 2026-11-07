-- 014_ticket_flow: the owner's ticket flow (Todo = picked from the backlog, which
-- starts enrichment; Ready for Dev = scope approved, which starts coding).
-- A run is either an enrichment run (makes the ticket self-contained, asks the
-- owner, never edits code) or a code run.
ALTER TABLE code_runs ADD COLUMN kind TEXT NOT NULL DEFAULT 'code';
