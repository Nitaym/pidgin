-- 008_token_usage_index: the Usage page reads model_invocations bucketed by
-- invoked_at (per-day / per-hour) and windowed by a `since` lower bound. The
-- existing idx_model_invocations_turn only helps the per-turn join, not these
-- time-range scans, so add an index on invoked_at to keep the usage queries
-- cheap once there is real invocation volume.
CREATE INDEX IF NOT EXISTS idx_model_invocations_invoked_at
  ON model_invocations(invoked_at);
