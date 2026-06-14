-- 004_slack_messaging.sql
-- Idempotency for inbound connector webhooks (Slack retries the same envelope
-- event_id when an ack is slow). A row here means "already ingested" — ingress
-- short-circuits duplicates instead of creating a second inbound_event.

CREATE TABLE connector_event_dedup (
  connector_type     TEXT NOT NULL,
  external_event_id  TEXT NOT NULL,
  inbound_event_id   TEXT,
  created_at         TEXT NOT NULL,
  PRIMARY KEY (connector_type, external_event_id)
);
