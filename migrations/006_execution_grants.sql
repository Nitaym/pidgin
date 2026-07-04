-- Execution grants (AUTONOMY / approvals): approving an agent's plan opens a
-- time-boxed grant so it can keep CREATING for that initiative without asking
-- again. Edits/deletes of resources it created under the grant are also covered;
-- edits/deletes of anything it did NOT create this session still stage for the
-- owner. See services/approvals (open_execution_grant) and gate_action.

CREATE TABLE agent_execution_grants (
  id                      TEXT PRIMARY KEY,
  ai_employee_id          TEXT NOT NULL,
  origin_approval_id      TEXT,
  granted_by_principal_id TEXT NOT NULL,
  status                  TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'revoked', 'expired')),
  granted_at              TEXT NOT NULL,
  expires_at              TEXT
);
CREATE INDEX idx_exec_grants_agent_active
  ON agent_execution_grants(ai_employee_id) WHERE status = 'active';

-- Resources the agent created while a grant was active. A later edit/delete
-- targeting one of these is the agent's own work and doesn't re-stage.
CREATE TABLE agent_grant_resources (
  id             TEXT PRIMARY KEY,
  grant_id       TEXT NOT NULL,
  ai_employee_id TEXT NOT NULL,
  resource_uri   TEXT NOT NULL,
  created_at     TEXT NOT NULL
);
CREATE INDEX idx_grant_resources_lookup
  ON agent_grant_resources(ai_employee_id, resource_uri);
