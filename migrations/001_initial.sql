-- Pidgin initial schema (24 tables)
-- FK constraints omitted in MVP migration to avoid circular dependency issues at CREATE time.
-- Application layer enforces referential integrity. See specs/SCHEMA_SPEC.md.

PRAGMA foreign_keys = ON;

CREATE TABLE workspace (
  id                          TEXT PRIMARY KEY,
  display_name                TEXT NOT NULL,
  hierarchy_recipe_id         TEXT,
  hierarchy_recipe_version    TEXT,
  default_marketplace_url     TEXT,
  debug_export_enabled        INTEGER NOT NULL DEFAULT 0,
  debug_export_retention_days INTEGER NOT NULL DEFAULT 7,
  settings_json               TEXT,
  created_at                  TEXT NOT NULL,
  updated_at                  TEXT NOT NULL
);

CREATE TABLE schema_migrations (
  version    TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL,
  checksum   TEXT NOT NULL
);

CREATE TABLE connector_installations (
  id               TEXT PRIMARY KEY,
  connector_type   TEXT NOT NULL,
  display_name     TEXT NOT NULL,
  credentials_json TEXT,
  config_json      TEXT,
  status           TEXT NOT NULL CHECK (status IN ('active', 'disabled', 'errored')),
  installed_at     TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  last_health_check_at TEXT,
  UNIQUE (connector_type, display_name)
);

CREATE TABLE principals (
  id                TEXT PRIMARY KEY,
  type              TEXT NOT NULL CHECK (type IN ('workspace_member', 'pidgin_agent', 'external_verified')),
  display_name      TEXT NOT NULL,
  email_address     TEXT,
  slack_user_id     TEXT,
  google_subject_id TEXT,
  ai_employee_id    TEXT,
  allowlist_pattern TEXT,
  is_active         INTEGER NOT NULL DEFAULT 1,
  metadata_json     TEXT,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  UNIQUE (email_address),
  UNIQUE (slack_user_id)
);
CREATE INDEX idx_principals_type ON principals(type);

CREATE TABLE ai_employees (
  id                       TEXT PRIMARY KEY,
  display_name             TEXT NOT NULL,
  role_title               TEXT NOT NULL,
  handle                   TEXT NOT NULL UNIQUE,
  recipe_snapshot_id       TEXT NOT NULL,
  human_owner_principal_id TEXT NOT NULL,
  manager_principal_id     TEXT,
  current_status           TEXT NOT NULL CHECK (current_status IN (
    'draft', 'interviewing', 'onboarding', 'active', 'paused', 'offboarded'
  )),
  permission_overrides_json TEXT,
  default_channels_json    TEXT,
  created_at               TEXT NOT NULL,
  updated_at               TEXT NOT NULL
);

CREATE TABLE ai_employees_status_log (
  id                 TEXT PRIMARY KEY,
  ai_employee_id     TEXT NOT NULL,
  from_status        TEXT,
  to_status          TEXT NOT NULL,
  actor_principal_id TEXT NOT NULL,
  reason             TEXT,
  occurred_at        TEXT NOT NULL
);
CREATE INDEX idx_ai_employees_status_log_employee
  ON ai_employees_status_log(ai_employee_id, occurred_at DESC);

CREATE TABLE ai_employee_recipe_snapshots (
  id             TEXT PRIMARY KEY,
  ai_employee_id TEXT NOT NULL,
  source_url     TEXT NOT NULL,
  recipe_id      TEXT NOT NULL,
  recipe_version TEXT NOT NULL,
  bundle_sha256  TEXT NOT NULL,
  bundle_json    TEXT NOT NULL,
  fetched_at     TEXT NOT NULL
);
CREATE INDEX idx_recipe_snapshots_employee
  ON ai_employee_recipe_snapshots(ai_employee_id, fetched_at DESC);

CREATE TABLE ingested_documents (
  id                       TEXT PRIMARY KEY,
  title                    TEXT NOT NULL,
  source_uri               TEXT,
  mime                     TEXT NOT NULL,
  blob_sha256              TEXT NOT NULL,
  text_path                TEXT NOT NULL,
  size_bytes               INTEGER NOT NULL,
  ingested_by_principal_id TEXT,
  metadata_json            TEXT,
  ingested_at              TEXT NOT NULL,
  updated_at               TEXT NOT NULL
);
CREATE INDEX idx_documents_sha256 ON ingested_documents(blob_sha256);

CREATE TABLE document_access_grants (
  id                      TEXT PRIMARY KEY,
  document_id             TEXT NOT NULL,
  ai_employee_id          TEXT NOT NULL,
  granted_by_principal_id TEXT NOT NULL,
  granted_at              TEXT NOT NULL,
  revoked_at              TEXT,
  UNIQUE (document_id, ai_employee_id)
);
CREATE INDEX idx_doc_access_employee_active
  ON document_access_grants(ai_employee_id) WHERE revoked_at IS NULL;

CREATE TABLE tasks (
  id                     TEXT PRIMARY KEY,
  title                  TEXT NOT NULL,
  description            TEXT,
  owner_principal_id     TEXT NOT NULL,
  source_conversation_id TEXT,
  source_turn_id         TEXT,
  current_status         TEXT NOT NULL DEFAULT 'open' CHECK (current_status IN (
    'open', 'in_progress', 'blocked', 'done', 'cancelled'
  )),
  outcome                TEXT,
  due_at                 TEXT,
  created_at             TEXT NOT NULL,
  updated_at             TEXT NOT NULL
);
CREATE INDEX idx_tasks_owner_status ON tasks(owner_principal_id, current_status);

CREATE TABLE tasks_status_log (
  id                 TEXT PRIMARY KEY,
  task_id            TEXT NOT NULL,
  from_status        TEXT,
  to_status          TEXT NOT NULL,
  actor_principal_id TEXT NOT NULL,
  reason             TEXT,
  occurred_at        TEXT NOT NULL
);
CREATE INDEX idx_tasks_status_log_task ON tasks_status_log(task_id, occurred_at);

CREATE TABLE conversations (
  id                 TEXT PRIMARY KEY,
  ai_employee_id     TEXT,
  modality           TEXT NOT NULL,
  external_thread_id TEXT,
  linked_task_id     TEXT,
  started_at         TEXT NOT NULL,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL,
  UNIQUE (modality, external_thread_id)
);
CREATE INDEX idx_conversations_agent ON conversations(ai_employee_id);

CREATE TABLE inbound_events (
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
    'pending', 'dispatching', 'done', 'failed'
  )),
  picked_up_at          TEXT,
  completed_at          TEXT,
  resulting_turn_id     TEXT,
  failure_reason        TEXT,
  received_at           TEXT NOT NULL
);
CREATE INDEX idx_inbound_events_pending
  ON inbound_events(received_at) WHERE processing_status = 'pending';
CREATE INDEX idx_inbound_events_employee
  ON inbound_events(target_ai_employee_id, received_at DESC);

CREATE TABLE turns (
  id                  TEXT PRIMARY KEY,
  ai_employee_id      TEXT NOT NULL,
  conversation_id     TEXT,
  triggering_event_id TEXT NOT NULL,
  parent_turn_id      TEXT,
  current_status      TEXT NOT NULL DEFAULT 'running' CHECK (current_status IN (
    'running', 'suspended', 'completed', 'failed', 'refused'
  )),
  suspension_reason   TEXT,
  started_at          TEXT NOT NULL,
  ended_at            TEXT
);
CREATE INDEX idx_turns_employee_started ON turns(ai_employee_id, started_at DESC);
CREATE INDEX idx_turns_active
  ON turns(current_status) WHERE current_status IN ('running', 'suspended');

CREATE TABLE turns_status_log (
  id          TEXT PRIMARY KEY,
  turn_id     TEXT NOT NULL,
  from_status TEXT,
  to_status   TEXT NOT NULL,
  reason      TEXT,
  occurred_at TEXT NOT NULL
);
CREATE INDEX idx_turns_status_log_turn ON turns_status_log(turn_id, occurred_at);

CREATE TABLE model_invocations (
  id                    TEXT PRIMARY KEY,
  turn_id               TEXT NOT NULL,
  sequence_in_turn      INTEGER NOT NULL,
  provider              TEXT NOT NULL,
  model_id              TEXT NOT NULL,
  request_messages_json TEXT NOT NULL,
  request_tools_json    TEXT,
  response_json         TEXT NOT NULL,
  input_tokens          INTEGER,
  output_tokens         INTEGER,
  cost_usd_micros       INTEGER,
  latency_ms            INTEGER,
  error_text            TEXT,
  invoked_at            TEXT NOT NULL,
  UNIQUE (turn_id, sequence_in_turn)
);
CREATE INDEX idx_model_invocations_turn ON model_invocations(turn_id, sequence_in_turn);

CREATE TABLE messages (
  id                   TEXT PRIMARY KEY,
  conversation_id      TEXT NOT NULL,
  sender_principal_id  TEXT NOT NULL,
  sender_display_name  TEXT NOT NULL,
  modality             TEXT NOT NULL,
  body_text            TEXT NOT NULL,
  body_format          TEXT NOT NULL DEFAULT 'text' CHECK (body_format IN ('text', 'markdown', 'html')),
  attachments_json     TEXT,
  originating_event_id   TEXT,
  originating_turn_id  TEXT,
  external_message_id  TEXT,
  created_at           TEXT NOT NULL
);
CREATE INDEX idx_messages_conversation_created ON messages(conversation_id, created_at);
CREATE INDEX idx_messages_external ON messages(modality, external_message_id);

CREATE TABLE agent_timers (
  id                    TEXT PRIMARY KEY,
  ai_employee_id        TEXT NOT NULL,
  scheduled_at          TEXT NOT NULL,
  reason                TEXT NOT NULL,
  originating_turn_id   TEXT NOT NULL,
  inherited_trust_label TEXT NOT NULL,
  status                TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'fired', 'cancelled')),
  fired_at              TEXT,
  fired_event_id        TEXT,
  created_at            TEXT NOT NULL,
  updated_at            TEXT NOT NULL
);
CREATE INDEX idx_agent_timers_pending ON agent_timers(scheduled_at) WHERE status = 'pending';
CREATE INDEX idx_agent_timers_employee ON agent_timers(ai_employee_id, status);

CREATE TABLE agent_watchers (
  id                            TEXT PRIMARY KEY,
  ai_employee_id                TEXT NOT NULL,
  resource_uri                  TEXT NOT NULL,
  until_condition               TEXT,
  reason                        TEXT NOT NULL,
  originating_turn_id           TEXT NOT NULL,
  inherited_trust_label         TEXT NOT NULL,
  connector_subscription_handle TEXT,
  status                        TEXT NOT NULL DEFAULT 'active' CHECK (status IN (
    'active', 'closed', 'expired', 'errored'
  )),
  closed_at                     TEXT,
  created_at                    TEXT NOT NULL,
  updated_at                    TEXT NOT NULL
);
CREATE INDEX idx_agent_watchers_active_employee
  ON agent_watchers(ai_employee_id) WHERE status = 'active';
CREATE INDEX idx_agent_watchers_resource ON agent_watchers(resource_uri);

CREATE TABLE pending_approvals (
  id                             TEXT PRIMARY KEY,
  ai_employee_id                 TEXT NOT NULL,
  originating_turn_id            TEXT NOT NULL,
  proposed_action                TEXT NOT NULL,
  proposed_action_params_json    TEXT NOT NULL,
  drafted_body                   TEXT,
  trust_label                    TEXT NOT NULL,
  requesting_principal_id        TEXT NOT NULL,
  requires_approver_principal_id TEXT NOT NULL,
  current_status                 TEXT NOT NULL DEFAULT 'open' CHECK (current_status IN (
    'open', 'approved', 'rejected', 'edited_and_approved', 'expired'
  )),
  resolution_event_id            TEXT,
  resolution_text                TEXT,
  resolved_at                    TEXT,
  expires_at                     TEXT,
  created_at                     TEXT NOT NULL
);
CREATE INDEX idx_pending_approvals_approver_open
  ON pending_approvals(requires_approver_principal_id) WHERE current_status = 'open';
CREATE INDEX idx_pending_approvals_turn ON pending_approvals(originating_turn_id);

CREATE TABLE pending_approvals_status_log (
  id                  TEXT PRIMARY KEY,
  pending_approval_id TEXT NOT NULL,
  from_status         TEXT,
  to_status           TEXT NOT NULL,
  actor_principal_id  TEXT,
  reason              TEXT,
  occurred_at         TEXT NOT NULL
);

CREATE TABLE external_intake_items (
  id                           TEXT PRIMARY KEY,
  ai_employee_id               TEXT NOT NULL,
  external_sender_principal_id TEXT NOT NULL,
  inbound_event_id             TEXT NOT NULL,
  summary                      TEXT,
  current_status               TEXT NOT NULL DEFAULT 'awaiting_adoption' CHECK (current_status IN (
    'awaiting_adoption', 'adopted', 'rejected', 'expired'
  )),
  adopting_principal_id        TEXT,
  adoption_event_id            TEXT,
  resolved_at                  TEXT,
  expires_at                   TEXT,
  created_at                   TEXT NOT NULL
);
CREATE INDEX idx_external_intake_employee_status
  ON external_intake_items(ai_employee_id, current_status);

CREATE TABLE quarantined_items (
  id                       TEXT PRIMARY KEY,
  ai_employee_id           TEXT NOT NULL,
  inbound_event_id         TEXT NOT NULL,
  trust_label              TEXT NOT NULL,
  reason                   TEXT NOT NULL,
  current_status           TEXT NOT NULL DEFAULT 'open' CHECK (current_status IN (
    'open', 'reviewed', 'summarized', 'expired'
  )),
  reviewed_by_principal_id TEXT,
  expires_at               TEXT,
  created_at               TEXT NOT NULL
);
CREATE INDEX idx_quarantined_employee_open
  ON quarantined_items(ai_employee_id) WHERE current_status = 'open';

CREATE TABLE agent_action_log (
  id                           TEXT PRIMARY KEY,
  turn_id                      TEXT NOT NULL,
  technical_actor              TEXT NOT NULL,
  virtual_actor_ai_employee_id TEXT NOT NULL,
  virtual_actor_display_name   TEXT NOT NULL,
  virtual_actor_role           TEXT NOT NULL,
  requester_principal_id       TEXT NOT NULL,
  requester_display_name       TEXT NOT NULL,
  approver                     TEXT,
  trust_label                  TEXT NOT NULL,
  policy_decision              TEXT NOT NULL CHECK (policy_decision IN (
    'accepted_as_instruction', 'routed_to_inbox', 'quarantined', 'auto_approved',
    'awaiting_human_approval', 'refused_by_policy', 'blocked'
  )),
  action_type                  TEXT NOT NULL,
  action_params_json           TEXT NOT NULL,
  target_system                TEXT,
  target_resource              TEXT,
  outcome                      TEXT NOT NULL CHECK (outcome IN ('executed', 'staged', 'refused', 'failed')),
  outcome_detail_json          TEXT,
  model_invocation_id          TEXT,
  occurred_at                  TEXT NOT NULL
);
CREATE INDEX idx_action_log_turn ON agent_action_log(turn_id, occurred_at);
CREATE INDEX idx_action_log_employee_time
  ON agent_action_log(virtual_actor_ai_employee_id, occurred_at DESC);
CREATE INDEX idx_action_log_outcome_time ON agent_action_log(outcome, occurred_at DESC);
CREATE INDEX idx_action_log_target ON agent_action_log(target_system, target_resource);
CREATE INDEX idx_action_log_policy_decision ON agent_action_log(policy_decision, occurred_at DESC);
