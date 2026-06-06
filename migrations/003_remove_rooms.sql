-- Drop internal rooms; agent DMs are conversations linked by ai_employee_id.
-- Slack/email channels are connector resources, not Pidgin rooms.

PRAGMA foreign_keys = OFF;

ALTER TABLE conversations ADD COLUMN ai_employee_id TEXT;

UPDATE conversations
SET ai_employee_id = (
  SELECT p.ai_employee_id
  FROM room_members rm
  INNER JOIN principals p ON p.id = rm.principal_id
  WHERE rm.room_id = conversations.room_id
    AND p.ai_employee_id IS NOT NULL
  LIMIT 1
)
WHERE room_id IS NOT NULL;

CREATE TABLE conversations_new (
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

INSERT INTO conversations_new (
  id, ai_employee_id, modality, external_thread_id, linked_task_id,
  started_at, created_at, updated_at
)
SELECT
  id, ai_employee_id, modality, external_thread_id, linked_task_id,
  started_at, created_at, updated_at
FROM conversations;

DROP TABLE conversations;
ALTER TABLE conversations_new RENAME TO conversations;
CREATE INDEX idx_conversations_agent ON conversations(ai_employee_id);

DROP TABLE room_members;
DROP TABLE rooms;

PRAGMA foreign_keys = ON;
