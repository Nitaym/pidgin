-- 013_run_tiles: ticket runs appear on the Devs page next to the owner's dev
-- terminals; a finished run's tile stays until the owner dismisses it.
ALTER TABLE code_runs ADD COLUMN dismissed_at TEXT;
