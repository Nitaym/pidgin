# Pidgin Schema Spec

## Summary

```text
Each Pidgin workspace is one SQLite file plus companion text files on disk. The schema is 26 tables grouped into 9 domains. Agent memory and document text live in files, not in the DB — the DB holds structure, pointers, and the audit trail.

For MVP the DB is plain SQLite. Each workspace has its own password, supplied by the caller at open time (Pidgin does not store or manage passwords). Full DB encryption and stronger secret injection (e.g. K8s secrets) are post-MVP.
```

The short product line:

```text
One file per workspace. One password per file (yours to keep). Twenty-six tables for structure; text files for memory.
```

> **Scope:** The per-workspace storage schema for the Pidgin runtime. Defines tables, columns, indexes, the append-only / mutable distinction, the storage and access model, and the conventions every table follows. Pairs with [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md), which defines how this state is produced and consumed.
>
> **Out of scope:** The recipe marketplace's own schema (separate app), workspace-level config files outside any DB, key management protocols (deferred to `SECURITY_PROTOCOLS_SPEC.md`), full DB encryption (deferred to post-MVP).

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [All Tables at a Glance](#2-all-tables-at-a-glance)
3. [Conventions](#3-conventions)
4. [Storage and Workspace Access](#4-storage-and-workspace-access)
5. [Group 1 — Tenant and Schema Infrastructure](#5-group-1--tenant-and-schema-infrastructure)
6. [Group 2 — Identity and Access](#6-group-2--identity-and-access)
7. [Group 3 — AI Employees](#7-group-3--ai-employees)
8. [Group 4 — Channels and Conversations](#8-group-4--channels-and-conversations)
9. [Group 5 — The Trigger Plane](#9-group-5--the-trigger-plane)
10. [Group 6 — Turns and Model Use](#10-group-6--turns-and-model-use)
11. [Group 7 — Work in Flight](#11-group-7--work-in-flight)
12. [Group 8 — Knowledge](#12-group-8--knowledge)
13. [Group 9 — The Action Record](#13-group-9--the-action-record)
14. [Caches and Frozen-at-Write Fields](#14-caches-and-frozen-at-write-fields)
15. [Schema Migrations](#15-schema-migrations)
16. [Open Decisions](#16-open-decisions)

---

## 1. Purpose

The runtime defined in [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) is stateless across restarts. **Structured operational state** lives in the DB; **long text** (agent memory, document bodies) lives in companion files on disk.

**In the DB:**

- Who works here (principals, AI employees)
- What they're allowed to do (recipe snapshots, permission profiles)
- What's happened (messages, events, turns, model calls, actions, status changes)
- What's in flight (timers, watchers, pending approvals, intake items, tasks)
- Catalog of ingested documents (metadata + file paths, not full text)
- The audit trail (every gate decision)

**On disk (per workspace directory):**

- Agent memory journals (`memory/<agent_handle>/journal.md`)
- Extracted document text (`docs/<document_id>.txt`)
- Original blobs (`blobs/...`)

Anything that could be computed from these sources is not stored as state. Caches are allowed and explicitly marked. Frozen-at-write fields (audit immutability) are explicitly marked.

---

## 2. All Tables at a Glance

The schema has **26 tables** across 9 groups, plus **file-based knowledge** (not tables). Each table is one of:

- **(A) Append-only** — only `INSERT`; no `UPDATE` or `DELETE` after a row is written.
- **(M) Mutable** — rows can be updated. Status lifecycles are paired with `*_status_log` tables.

Full details (columns, indexes, constraints, lifecycle notes) for each table are in sections 5 through 13. Conventions that apply to every table are in §3. The storage and access model is in §4.

| # | Table | Type | Purpose |
|---|---|---|---|
| **Group 1 — Tenant and Schema Infrastructure** (§5) | | | |
| 1 | `workspace` | M | Single-row settings for this workspace |
| 2 | `schema_migrations` | A | Applied migration ledger |
| **Group 2 — Identity and Access** (§6) | | | |
| 3 | `principals` | M | Directory of humans, AI employees, and allowlisted externals |
| 4 | `connector_installations` | M | Per-workspace integration configs and credentials |
| 5 | `document_access_grants` | M | Which AI employees can read which documents |
| **Group 3 — AI Employees** (§7) | | | |
| 6 | `ai_employees` | M | Instantiated AI employees with cached `current_status` |
| 7 | `ai_employees_status_log` | A | Lifecycle transitions per AI employee |
| 8 | `ai_employee_recipe_snapshots` | A | Immutable recipe bundles snapshotted at hire time |
| **Group 4 — Channels and Conversations** (§8) | | | |
| 9 | `rooms` | M | Channels and rooms (Slack channels, internal rooms, DMs, email threads) |
| 10 | `room_members` | M | Membership of rooms (humans + agents) |
| 11 | `conversations` | M | Threads — DMs, room threads, email threads, ticket threads |
| 12 | `messages` | A | Every utterance in every conversation (sender display name frozen-at-write) |
| **Group 5 — The Trigger Plane** (§9) | | | |
| 13 | `inbound_events` | A\* | The durable inbound queue — one row per trigger firing |
| 14 | `agent_timers` | M | Pending self-prompts and recurring schedules |
| 15 | `agent_watchers` | M | Subscriptions to connector resources |
| **Group 6 — Turns and Model Use** (§10) | | | |
| 16 | `turns` | M | Anchor for `run_id` with cached `current_status` |
| 17 | `turns_status_log` | A | Status transitions per turn |
| 18 | `model_invocations` | A | Per-LLM-call record (cost, tokens, latency, raw I/O) |
| **Group 7 — Work in Flight** (§11) | | | |
| 19 | `tasks` | M | Structured work items with cached `current_status` |
| 20 | `tasks_status_log` | A | Status transitions per task |
| 21 | `pending_approvals` | M | Actions staged for owner approval |
| 22 | `pending_approvals_status_log` | A | Status transitions per approval |
| 23 | `external_intake_items` | M | External-verified requests awaiting commander adoption |
| 24 | `quarantined_items` | M | Untrusted / unverified items flagged for owner review |
| **Group 8 — Knowledge** (§12) | | | |
| 25 | `ingested_documents` | M | Catalog of ingested documents (metadata + paths to text files on disk) |
| **Group 9 — The Action Record** (§13) | | | |
| 26 | `agent_action_log` | A | Single source of truth for every gated action (frozen-at-write attribution) |

**File-based (not tables, MVP):**

| Path | Purpose |
|---|---|
| `memory/<agent_handle>/journal.md` | Per-agent append-only memory journal (`remember` / `recall`) |
| `docs/<document_id>.txt` | Extracted text for an ingested document |
| `blobs/<ab>/<cd>/<sha256>` | Original uploaded/ingested files |
| `role-templates/<slug>/manifest.json` | Workspace role template metadata (see §4.1.1) |
| `role-templates/<slug>/v<N>.md` | Versioned role brief body (Markdown + YAML frontmatter) |
| `hr-assist/sessions/<session_id>/meta.json` | HR assist session metadata (see §4.1.2) |
| `hr-assist/sessions/<session_id>/messages.jsonl` | HR assist chat transcript (append-only JSONL) |
| `audit/brief-edits/<employee_id>.jsonl` | Post-hire brief edit audit trail (see §4.1.3) |
| `audit/template-versions/<slug>.jsonl` | Workspace template version-create audit trail |

\* `inbound_events` is append-only for payload and trigger metadata; `processing_status` and three companion operational fields are mutable. This is the one declared exception to strict append-only — see §9 for the rationale.

**Deferred post-MVP (not in MVP schema):** vector embeddings (`sqlite-vec`), `document_chunks`, DB-backed `ai_employee_memory_entries`. Search improves on the file layer first (grep, FTS, then vectors if needed).

### 2.1 Reading the schema

- **Start with Group 9 (`agent_action_log`)** to understand the audit surface — most other tables exist to support it.
- **Then Group 5 and Group 6** to see how triggers become turns become actions.
- **Then Groups 3, 7, 8** for the entities triggers and turns operate on.
- **Groups 1, 2, 4** are infrastructure that supports the rest.

### 2.2 Append-only vs. mutable map

For implementers: this is the list to wire into the repository layer's allow-list of operations.

| Append-only (insert only) | Mutable (insert + update) |
|---|---|
| `schema_migrations` | `workspace` |
| `ai_employees_status_log` | `principals` |
| `ai_employee_recipe_snapshots` | `connector_installations` |
| `messages` | `document_access_grants` |
| `turns_status_log` | `ai_employees` |
| `model_invocations` | `rooms` |
| `tasks_status_log` | `room_members` |
| `pending_approvals_status_log` | `conversations` |
| `agent_action_log` | `inbound_events` (partial) |
| | `agent_timers` |
| | `agent_watchers` |
| | `turns` |
| | `tasks` |
| | `pending_approvals` |
| | `external_intake_items` |
| | `quarantined_items` |
| | `ingested_documents` |

---

## 3. Conventions

### 3.1 Naming

- **Plural snake_case** for table names: `agent_timers`, not `agent_timer` or `agentTimers`.
- **Prefix by subject domain** when the bare noun is ambiguous: `ai_employee_*`, `agent_*`, `connector_*`, `document_*`.
- **`_log` suffix** for append-only event/status logs: `ai_employees_status_log`, `tasks_status_log`.
- **Match spec vocabulary exactly** where defined elsewhere: `principals` (per SECURITY_SPEC), `ai_employees` (per PRODUCT_SPEC), `agent_action_log` (per INTEGRATION_WOFKLOW + SECURITY_SPEC).

### 3.2 Primary keys

- **ULIDs everywhere.** Stored as `TEXT` (26 chars). Globally unique, lexicographically sortable by creation time, no integer-PK leakage, safe for any future merges or migrations.
- No auto-increment integer PKs except where measured performance demands it (none in MVP).

### 3.3 Timestamps

- **All timestamps UTC, ISO 8601 with millisecond precision, stored as `TEXT`.**
- Example: `2026-05-29T18:23:04.123Z`.
- Switches cleanly to PostgreSQL `TIMESTAMPTZ` later.
- Every table has `created_at`. Mutable tables also have `updated_at`. Append-only tables do not.

### 3.4 Append-only vs. mutable

Each table is classified as:

- **Append-only (A):** rows are only ever inserted. The data-access layer exposes only `insert(...)`, never `update(...)` or `delete(...)`. This is enforced at the repository boundary.
- **Mutable (M):** rows can be updated; `updated_at` reflects the latest change. Lifecycle is captured separately in a paired `_status_log` table if the entity has meaningful states.

### 3.5 Status as event-sourced, current state as cache

Four entities have meaningful status lifecycles: `ai_employees`, `tasks`, `pending_approvals`, `turns`.

For each one:

- A `*_status_log` append-only table records every status change.
- The parent table holds a `current_status` column. **This is a cache** — computed as the latest `to_status` from the log. Documented and rebuildable.

All status changes go through one helper that writes the log row AND updates the cache atomically. No naked `UPDATE ai_employees SET current_status = ...` anywhere in the codebase.

### 3.6 JSON discipline

- JSON fields allowed for genuinely variable payloads: `inbound_events.payload_json`, `pending_approvals.proposed_action_params_json`, `model_invocations.request_messages_json`.
- **Anything we will ever filter or join on gets its own column**, not a JSON path. SQLite generated columns + indexes are an option when we want both.

### 3.7 Frozen-at-write fields

Some columns intentionally denormalize a value at write time and **must never be updated even if the source changes**. These are audit-immutability fields, not caches.

Examples: `messages.sender_display_name`, `agent_action_log.virtual_actor_display_name`, `agent_action_log.requester_display_name`. A message from 2026 must still show its sender's name as it was when sent, regardless of later renames or deletions.

Frozen-at-write columns are marked explicitly in each table's notes below.

### 3.8 Foreign keys and constraints

- `FOREIGN KEY` declarations on every cross-table reference.
- `CHECK` constraints for enum-style columns.
- `UNIQUE` constraints for natural identifiers.
- `PRAGMA foreign_keys = ON` required at every connection open.

---

## 4. Storage and Workspace Access

### 4.1 Storage model for MVP

Each workspace is **one directory** containing:

- `db.sqlite` — plain SQLite (structured operational data)
- `memory/` — per-agent text journals
- `docs/` — extracted document text
- `blobs/` — original files
- `auth.json` — password verifier only (see §4.2)
- `role-templates/` — **Your role templates** (text files, not DB; see §4.1.1)
- `hr-assist/sessions/` — HR assist chat sessions (file-based; see §4.1.2)
- `audit/` — file-based audit for hire UX (brief edits, template versions; see §4.1.3)

Workspaces are isolated by **file separation**. Each workspace has its **own password**, but **Pidgin does not store or manage that password** — the caller supplies it when opening a workspace (CLI flag, environment variable, or interactive prompt). For MVP, where the operator keeps the password is their problem (password manager, `.env` file, sticky note). For production deployment, passwords come from a proper secret store (e.g. Kubernetes Secret, Vault) injected at runtime.

**Not in MVP:** OS keychain integration, Argon2id/AES credential encryption, SQLCipher full-DB encryption, vector search. These are post-MVP upgrades.

#### 4.1.1 Workspace role templates (locked — files, not DB)

**Your role templates** live under `role-templates/<slug>/`. Pidgin role templates remain bundled JSON in `recipes/*.json` ([RECIPES_SPEC.md](RECIPES_SPEC.md)); duplicating into the workspace creates a new slug folder starting at `v1.md`.

```
role-templates/
  <slug>/
    manifest.json       # metadata; points at current_version
    v1.md               # version 1 body
    v2.md               # version 2 body (prior versions never overwritten)
    ...
```

**Manifest schema** (`manifest.json`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | yes | Display name shown in UI |
| `slug` | string | yes | Directory name; kebab-case; stable across versions |
| `current_version` | integer | yes | Latest version number; matches highest `v<N>.md` |
| `created_at` | string | yes | UTC ISO 8601 ms |
| `updated_at` | string | yes | UTC ISO 8601 ms; bumped on every new version |
| `lineage` | object | no | Provenance when copied from Pidgin template or agent |

Optional `lineage` keys:

| Key | Type | When set |
|---|---|---|
| `source_recipe_id` | string | Duplicated from bundled Pidgin role template |
| `source_recipe_version` | string | Semver of bundled template at duplicate time |
| `derived_from_agent_id` | string | Created via “Create template from agent” |
| `derived_from_agent_handle` | string | Human-readable handle for UI lineage note |

**Version body format (locked):** Markdown with YAML frontmatter. Each save under the **same slug** writes a **new** `v<N>.md` file; prior version files are never edited or deleted except on explicit template delete (entire slug folder).

Example `v2.md`:

```markdown
---
version: 2
created_at: 2026-05-31T10:00:00.000Z
created_by_principal_id: 01J...
---

## Job requirements

### Mission
…

### Responsibilities
- …

### Out of scope
- …

## Ideal candidate profile

### Tone
…

### Decision framework
…

### Escalation rules
…

## Your take
…
```

**Version promotion:** saving with unchanged `name` / `slug` increments `current_version`, writes `v{N+1}.md`, updates `manifest.updated_at`. The UI shows the latest version as current; older files remain browsable.

**API mapping:** `GET/POST/PATCH .../role-templates` read and write these files — see [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) Hire UX API routes.

#### 4.1.2 HR assist sessions (locked — files, not DB)

HR assist chat threads persist under `hr-assist/sessions/<session_id>/`:

```
hr-assist/sessions/
  <session_id>/
    meta.json
    messages.jsonl
```

`session_id` is a ULID. `meta.json`:

| Field | Type | Required | Notes |
|---|---|---|---|
| `session_id` | string | yes | Same as directory name |
| `context_type` | string | yes | `hire` \| `agent` \| `template` |
| `context_id` | string | yes | Hire session ULID, `ai_employees.id`, or template `slug` |
| `created_at` | string | yes | UTC ISO 8601 ms |
| `updated_at` | string | yes | Bumped on each message append |

`messages.jsonl` — one JSON object per line (append-only):

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Message ULID |
| `role` | string | yes | `operator` \| `assist` |
| `body_text` | string | yes | Plain text |
| `created_at` | string | yes | UTC ISO 8601 ms |
| `suggestion` | object | no | Present on `assist` messages when actionable |

**Suggestion payload** (for **Apply to form** / **Append to your take**):

```json
{
  "action": "apply",
  "targets": {
    "job_requirements.mission": "…",
    "ideal_candidate.tone": "…"
  }
}
```

| `action` | Behavior |
|---|---|
| `apply` | Overwrite listed dot-path keys in the active form (`targets` map) |
| `append_your_take` | Append `targets.your_take` (string) to the **Your take** field with a newline separator |

Dot-path keys match [§7.1](#71-hire_customization_json) field names. UI may ignore unknown keys; backend validates paths on apply.

**API:** `POST .../hr-assist/sessions`, `POST/GET .../hr-assist/sessions/{id}/messages` — see [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

#### 4.1.3 Hire UX audit files (locked — files, not DB)

Post-hire brief edits and workspace template version creates append to JSONL audit files (not `agent_action_log` — those remain for gated agent actions).

| Path | When written |
|---|---|
| `audit/brief-edits/<employee_id>.jsonl` | Each save of job requirements, ideal candidate, or your take on an agent profile |
| `audit/template-versions/<slug>.jsonl` | Each new `v<N>.md` created for a workspace template |

Each JSONL line:

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Audit entry ULID |
| `occurred_at` | string | yes | UTC ISO 8601 ms |
| `actor_principal_id` | string | yes | Operator who performed the action |
| `action` | string | yes | `brief_edit` \| `template_version_create` |
| `summary` | string | yes | Human-readable one-liner for UI |
| `changes_json` | string | no | JSON string: field-level diff or `{ "from_version": 1, "to_version": 2 }` |

### 4.2 Workspace password (verify only, never store)

At workspace creation:

1. User chooses a password.
2. Runtime stores a **bcrypt hash** in `auth.json` (along with workspace id and creation metadata).
3. The password itself is **never written to disk** by Pidgin.

At open:

1. Caller provides the password (e.g. `pidgin open --workspace acme --password "$ACME_DB_PASSWORD"`).
2. Runtime verifies against the bcrypt hash in `auth.json`.
3. If match → open `db.sqlite`. If not → refuse.
4. Password exists in process memory only for the duration of the open session, then is discarded.

`auth.json` example:

```json
{
  "workspace_id": "01J...",
  "password_hash": "$2b$12$...",
  "created_at": "2026-05-30T12:00:00.000Z"
}
```

### 4.3 What is encrypted (MVP: nothing)

| Data | MVP storage | Post-MVP option |
|---|---|---|
| DB tables | Plaintext SQLite | SQLCipher with workspace password as key |
| Connector credentials | Plaintext in `connector_installations.credentials_json` | Encrypt at rest when DB encryption lands |
| Memory / doc text files | Plain markdown / text on disk | Optional encryption under workspace key |
| Workspace password | **Not stored** — hash in `auth.json` only | Same; production injects password from secret store |

MVP trade-off: anyone with read access to the workspace directory can read everything, including connector tokens. Acceptable for local single-user / trusted-team deployment. Not acceptable for multi-tenant SaaS without the post-MVP encryption path.

### 4.4 Workspace lifecycle commands

| Operation | Effect |
|---|---|
| `create_workspace(name, password)` | Hash password → write `auth.json`; create directory layout; create `db.sqlite`; initialize schema; register in runtime registry |
| `open_workspace(id, password)` | Verify password against `auth.json`; open DB; return scoped connection |
| `close_workspace(id)` | Close DB; discard password from memory |
| `list_workspaces()` | Enumerate registry — no password required to list, only to open |
| `change_password(id, old, new)` | Verify old password; rewrite bcrypt hash in `auth.json` |
| `export_workspace(id)` | Bundle workspace directory as portable archive |
| `delete_workspace(id)` | Remove workspace directory and registry entry |

### 4.5 File-based knowledge layout

```
workspaces/<workspace_id>/
  auth.json
  db.sqlite
  memory/
    jane/
      journal.md              ← append-only; one line per remember()
    max/
      journal.md
  docs/
    01J....txt                ← extracted text; id matches ingested_documents.id
  blobs/
    ab/cd/<sha256>            ← original files
  role-templates/
    support-lead/
      manifest.json
      v1.md
      v2.md
  hr-assist/
    sessions/
      01J.../
        meta.json
        messages.jsonl
  audit/
    brief-edits/
      01J....jsonl            ← one file per ai_employees.id
    template-versions/
      support-lead.jsonl      ← one file per template slug
  _debug/                     ← optional debug export
```

**Agent memory (`remember` / `recall`):** append a dated entry to `memory/<handle>/journal.md`. **Recall** reads the tail of the journal (last N lines / last N KB) and optionally greps for keywords from the current turn. No DB table, no embeddings.

**Documents:** on ingest, write extracted text to `docs/<id>.txt`; DB row in `ingested_documents` holds metadata and `text_path`. **Recall** greps across granted doc files or reads relevant files whole if small enough.

Search infrastructure (FTS, ripgrep index, vectors) improves on this file layer later — the MVP path is deliberately boring text files.

### 4.6 Runtime-level (workspace-agnostic) state

```
~/.pidgin/
  config.json                 ← runtime settings (marketplace URLs, defaults)
  workspaces_registry.json    ← list of known workspaces: id, display name, directory path
  workspaces/
    <workspace_id>/           ← per §4.5
```

### 4.7 Forward path (post-MVP)

| Upgrade | Trigger |
|---|---|
| SQLCipher on `db.sqlite` | Multi-tenant or untrusted disk |
| Credential encryption | Same |
| FTS / vector index on `memory/` and `docs/` | Volume makes grep too slow |
| Secret injection adapter | Production K8s / Vault deployment |

### 4.8 Debug export

The flag-controlled debug export (per [AGENT_RUNTIME_SPEC §10.2](AGENT_RUNTIME_SPEC.md)) writes plaintext markdown / text files under `_debug/`. Off by default, opt-in per workspace, auto-purged after configurable retention.

---

## 5. Group 1 — Tenant and Schema Infrastructure

### `workspace` (M)

Single-row table holding this workspace's settings.

```sql
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
```

Notes: Single-row by convention. The `id` is the workspace ULID, matching the directory name on disk.

### `schema_migrations` (A)

Tracks applied migrations.

```sql
CREATE TABLE schema_migrations (
  version    TEXT PRIMARY KEY,        -- e.g. "001_initial"
  applied_at TEXT NOT NULL,
  checksum   TEXT NOT NULL            -- sha256 of the migration SQL
);
```

---

## 6. Group 2 — Identity and Access

### `principals` (M)

The workspace directory: every actor that can send a message to an agent.

```sql
CREATE TABLE principals (
  id                 TEXT PRIMARY KEY,
  type               TEXT NOT NULL CHECK (type IN (
                       'workspace_member',
                       'pidgin_agent',
                       'external_verified'
                     )),
  display_name       TEXT NOT NULL,
  email_address      TEXT,
  slack_user_id      TEXT,
  google_subject_id  TEXT,
  ai_employee_id     TEXT,                  -- non-NULL iff type='pidgin_agent'
  allowlist_pattern  TEXT,                  -- for external_verified, e.g. 'domain:acme.com'
  is_active          INTEGER NOT NULL DEFAULT 1,
  metadata_json      TEXT,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL,
  UNIQUE (email_address),
  UNIQUE (slack_user_id),
  FOREIGN KEY (ai_employee_id) REFERENCES ai_employees(id)
);
CREATE INDEX idx_principals_type ON principals(type);
```

Notes: `external_unverified` and `untrusted_content` are *not* rows here; they're the absence-of-a-row case classified by the runtime at event ingress.

### `connector_installations` (M)

Per-workspace integration installs.

```sql
CREATE TABLE connector_installations (
  id                    TEXT PRIMARY KEY,
  connector_type        TEXT NOT NULL,            -- 'slack', 'gmail', 'jira', ...
  display_name          TEXT NOT NULL,
  credentials_json          TEXT,                     -- OAuth tokens, API keys (plaintext for MVP)
  config_json           TEXT,                     -- non-secret config (URLs, team IDs)
  status                TEXT NOT NULL CHECK (status IN (
                          'active', 'disabled', 'errored'
                        )),
  installed_at          TEXT NOT NULL,
  updated_at            TEXT NOT NULL,
  last_health_check_at  TEXT,
  UNIQUE (connector_type, display_name)
);
```

Notes: MVP stores connector credentials as plaintext JSON in the DB. Protect the workspace directory. Post-MVP: encrypt when SQLCipher lands.

### `document_access_grants` (M)

Which AI employees can read which ingested documents.

```sql
CREATE TABLE document_access_grants (
  id                       TEXT PRIMARY KEY,
  document_id              TEXT NOT NULL,
  ai_employee_id           TEXT NOT NULL,
  granted_by_principal_id  TEXT NOT NULL,
  granted_at               TEXT NOT NULL,
  revoked_at               TEXT,
  UNIQUE (document_id, ai_employee_id),
  FOREIGN KEY (document_id) REFERENCES ingested_documents(id),
  FOREIGN KEY (ai_employee_id) REFERENCES ai_employees(id),
  FOREIGN KEY (granted_by_principal_id) REFERENCES principals(id)
);
CREATE INDEX idx_doc_access_employee_active
  ON document_access_grants(ai_employee_id) WHERE revoked_at IS NULL;
```

---

## 7. Group 3 — AI Employees

### `ai_employees` (M; `current_status` cached)

Instantiated AI employees.

```sql
CREATE TABLE ai_employees (
  id                         TEXT PRIMARY KEY,
  display_name               TEXT NOT NULL,
  role_title                 TEXT NOT NULL,
  handle                     TEXT NOT NULL UNIQUE,    -- e.g. 'jane'
  recipe_snapshot_id         TEXT NOT NULL,
  human_owner_principal_id   TEXT NOT NULL,
  manager_principal_id       TEXT,
  current_status             TEXT NOT NULL CHECK (current_status IN (
                               'draft', 'interviewing', 'onboarding',
                               'active', 'paused', 'offboarded'
                             )),
  permission_overrides_json  TEXT,                    -- merged on top of recipe at gate time
  hire_customization_json   TEXT,                    -- operator brief; see §7.1
  default_channels_json      TEXT,                    -- email alias, slack handle
  created_at                 TEXT NOT NULL,
  updated_at                 TEXT NOT NULL,
  FOREIGN KEY (recipe_snapshot_id) REFERENCES ai_employee_recipe_snapshots(id),
  FOREIGN KEY (human_owner_principal_id) REFERENCES principals(id),
  FOREIGN KEY (manager_principal_id) REFERENCES principals(id)
);
```

Notes: `current_status` is a cache of the latest row in `ai_employees_status_log`. The **resolved permission profile** (effective `can_read`/`can_write`/`requires_approval`/`blocked`) is *not stored* — computed at gate time from `recipe_snapshot.bundle_json` + `permission_overrides_json`.

`hire_customization_json` holds the operator-editable brief (job requirements, ideal candidate profile, your take). It is **mutable** after hire; the immutable `ai_employee_recipe_snapshots` row is never updated for brief changes. See §7.1.

### 7.1 `hire_customization_json`

JSON object persisted on `ai_employees` at hire and updated on post-hire profile saves ([MVP_USER_STORIES.md](MVP_USER_STORIES.md) US-6, US-9). Shape aligns with hire wizard and agent profile fields:

```json
{
  "job_requirements": {
    "mission": "string",
    "responsibilities": ["string"],
    "out_of_scope": ["string"]
  },
  "ideal_candidate": {
    "tone": "string",
    "decision_framework": "string",
    "escalation_rules": "string"
  },
  "your_take": "string"
}
```

| Field | Type | Notes |
|---|---|---|
| `job_requirements.mission` | string | Primary purpose of the role |
| `job_requirements.responsibilities` | string[] | Ordered list; empty array allowed |
| `job_requirements.out_of_scope` | string[] | Explicit boundaries |
| `ideal_candidate.tone` | string | Communication style |
| `ideal_candidate.decision_framework` | string | How the agent should decide |
| `ideal_candidate.escalation_rules` | string | When and how to escalate |
| `your_take` | string | Freeform operator additions |

**Pre-fill at hire:** bundled recipe `default_job_requirements` and `default_ideal_candidate` ([RECIPES_SPEC.md](RECIPES_SPEC.md) §2) seed the wizard; operator edits are written to this column at hire. Workspace template `v<N>.md` bodies parse into the same shape.

**Post-hire edits:** `PATCH .../agents/{handle}/brief` (or equivalent) replaces the full object or merges sections; each save appends to `audit/brief-edits/<employee_id>.jsonl` (§4.1.3).

### 7.2 Resolved system prompt merge (turn time)

At turn time the runtime builds the agent system prompt from the **immutable recipe snapshot** plus the **mutable customization**. Merge order (locked):

1. **Base template** — `bundle_json.system_prompt_template` from `ai_employees.recipe_snapshot_id`.
2. **Placeholder render** — substitute `{{display_name}}`, `{{role_title}}`, and other recipe-defined placeholders from the `ai_employees` row (and workspace context as defined in [RECIPES_SPEC.md](RECIPES_SPEC.md)).
3. **Customization append** — if `hire_customization_json` is non-null, append a fixed markdown section block:

```markdown

---

## Job requirements (operator-defined)

**Mission:** {mission}

**Responsibilities:**
- {responsibility_1}
- …

**Out of scope:**
- {item_1}
- …

## Ideal candidate profile (operator-defined)

**Tone:** {tone}

**Decision framework:** {decision_framework}

**Escalation rules:** {escalation_rules}

## Your take

{your_take}
```

Omit subsections whose source field is empty or missing. Lists render as markdown bullets; empty arrays omit the subsection heading.

4. **Runtime injections** — time, recall context, pending timers/watchers per [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) §4 append after the merged system prompt.

The merged prompt is **not stored** — derived on each turn. `model_invocations.request_messages_json` captures what was actually sent.

**Invariant:** customization changes affect subsequent turns immediately; they never mutate `ai_employee_recipe_snapshots.bundle_json`.

### `ai_employees_status_log` (A)

Lifecycle transitions.

```sql
CREATE TABLE ai_employees_status_log (
  id                  TEXT PRIMARY KEY,
  ai_employee_id      TEXT NOT NULL,
  from_status         TEXT,                          -- NULL for initial creation
  to_status           TEXT NOT NULL,
  actor_principal_id  TEXT NOT NULL,
  reason              TEXT,
  occurred_at         TEXT NOT NULL,
  FOREIGN KEY (ai_employee_id) REFERENCES ai_employees(id),
  FOREIGN KEY (actor_principal_id) REFERENCES principals(id)
);
CREATE INDEX idx_ai_employees_status_log_employee
  ON ai_employees_status_log(ai_employee_id, occurred_at DESC);
```

### `ai_employee_recipe_snapshots` (A)

Immutable frozen recipe bundles snapshotted from the marketplace at hire time.

```sql
CREATE TABLE ai_employee_recipe_snapshots (
  id              TEXT PRIMARY KEY,
  ai_employee_id  TEXT NOT NULL,
  source_url      TEXT NOT NULL,
  recipe_id       TEXT NOT NULL,                     -- e.g. 'support-agent'
  recipe_version  TEXT NOT NULL,                     -- e.g. 'v1.2'
  bundle_sha256   TEXT NOT NULL,                     -- cache, recomputable
  bundle_json     TEXT NOT NULL,                     -- full frozen recipe content
  fetched_at      TEXT NOT NULL,
  FOREIGN KEY (ai_employee_id) REFERENCES ai_employees(id)
);
CREATE INDEX idx_recipe_snapshots_employee
  ON ai_employee_recipe_snapshots(ai_employee_id, fetched_at DESC);
```

Notes: Upgrading an agent to a new recipe version creates a NEW row here, not an edit to the old one. The `ai_employees.recipe_snapshot_id` pointer is updated to point at the new snapshot. Old snapshots are retained for audit.

---

## 8. Group 4 — Channels and Conversations

### `rooms` (M)

Channels/rooms — Slack channels, internal Pidgin rooms, email aliases, DM buckets.

```sql
CREATE TABLE rooms (
  id                   TEXT PRIMARY KEY,
  name                 TEXT NOT NULL UNIQUE,
  purpose              TEXT,
  modality             TEXT NOT NULL CHECK (modality IN (
                         'pidgin_chat', 'slack', 'email_thread', 'jira', 'other'
                       )),
  external_system_id   TEXT,                         -- e.g. Slack channel ID
  visibility           TEXT NOT NULL CHECK (visibility IN (
                         'public', 'private', 'dm'
                       )),
  created_at           TEXT NOT NULL,
  updated_at           TEXT NOT NULL,
  UNIQUE (modality, external_system_id)
);
```

### `room_members` (M)

Membership of rooms.

```sql
CREATE TABLE room_members (
  id                          TEXT PRIMARY KEY,
  room_id                     TEXT NOT NULL,
  principal_id                TEXT NOT NULL,
  channel_activity_subscribed INTEGER NOT NULL DEFAULT 0,  -- trigger 2 opt-in
  muted                       INTEGER NOT NULL DEFAULT 0,
  joined_at                   TEXT NOT NULL,
  UNIQUE (room_id, principal_id),
  FOREIGN KEY (room_id) REFERENCES rooms(id),
  FOREIGN KEY (principal_id) REFERENCES principals(id)
);
CREATE INDEX idx_room_members_principal ON room_members(principal_id);
```

### `conversations` (M)

Threads — DMs, room threads, email threads, ticket threads.

```sql
CREATE TABLE conversations (
  id                  TEXT PRIMARY KEY,
  room_id             TEXT,                          -- NULL for cross-room or DM-only
  modality            TEXT NOT NULL,
  external_thread_id  TEXT,                          -- e.g. Slack thread_ts, email Message-ID root
  linked_task_id      TEXT,
  started_at          TEXT NOT NULL,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  UNIQUE (modality, external_thread_id),
  FOREIGN KEY (room_id) REFERENCES rooms(id),
  FOREIGN KEY (linked_task_id) REFERENCES tasks(id)
);
CREATE INDEX idx_conversations_room ON conversations(room_id);
```

Notes: `last_activity_at` is **not stored** — derived as `MAX(messages.created_at)` for the conversation, served via the index on `messages`.

### `messages` (A; `sender_display_name` frozen-at-write)

Every utterance in every conversation.

```sql
CREATE TABLE messages (
  id                    TEXT PRIMARY KEY,
  conversation_id       TEXT NOT NULL,
  sender_principal_id   TEXT NOT NULL,
  sender_display_name   TEXT NOT NULL,               -- FROZEN AT WRITE
  modality              TEXT NOT NULL,
  body_text             TEXT NOT NULL,
  body_format           TEXT NOT NULL DEFAULT 'text' CHECK (body_format IN (
                          'text', 'markdown', 'html'
                        )),
  attachments_json      TEXT,                        -- array of document IDs
  originating_event_id  TEXT,
  originating_turn_id   TEXT,                        -- non-NULL if sent by an agent
  external_message_id   TEXT,                        -- Slack ts, email Message-ID
  created_at            TEXT NOT NULL,
  FOREIGN KEY (conversation_id) REFERENCES conversations(id),
  FOREIGN KEY (sender_principal_id) REFERENCES principals(id),
  FOREIGN KEY (originating_event_id) REFERENCES inbound_events(id),
  FOREIGN KEY (originating_turn_id) REFERENCES turns(id)
);
CREATE INDEX idx_messages_conversation_created
  ON messages(conversation_id, created_at);
CREATE INDEX idx_messages_external
  ON messages(modality, external_message_id);
```

---

## 9. Group 5 — The Trigger Plane

### `inbound_events` (M for `processing_status`; otherwise insert-once)

The durable inbound queue. One row per trigger firing.

```sql
CREATE TABLE inbound_events (
  id                       TEXT PRIMARY KEY,
  trigger_type             TEXT NOT NULL CHECK (trigger_type IN (
                             'direct_address', 'channel_activity', 'inbound_external',
                             'timer', 'watcher', 'self_prompt',
                             'peer_delegation', 'approval_response'
                           )),
  target_ai_employee_id    TEXT,
  sender_principal_id      TEXT,                     -- NULL for timer firings, etc.
  trust_label              TEXT NOT NULL CHECK (trust_label IN (
                             'internal-authenticated',
                             'external-verified',
                             'external-unverified',
                             'untrusted-content'
                           )),
  resumes_turn_id          TEXT,                     -- non-NULL for trigger 8
  parent_turn_id           TEXT,                     -- for delegate sub-turns
  payload_json             TEXT NOT NULL,
  processing_status        TEXT NOT NULL DEFAULT 'pending' CHECK (processing_status IN (
                             'pending', 'dispatching', 'done', 'failed'
                           )),
  picked_up_at             TEXT,
  completed_at             TEXT,
  resulting_turn_id        TEXT,
  failure_reason           TEXT,
  received_at              TEXT NOT NULL,
  FOREIGN KEY (target_ai_employee_id) REFERENCES ai_employees(id),
  FOREIGN KEY (sender_principal_id) REFERENCES principals(id),
  FOREIGN KEY (resumes_turn_id) REFERENCES turns(id),
  FOREIGN KEY (parent_turn_id) REFERENCES turns(id),
  FOREIGN KEY (resulting_turn_id) REFERENCES turns(id)
);
CREATE INDEX idx_inbound_events_pending
  ON inbound_events(received_at) WHERE processing_status = 'pending';
CREATE INDEX idx_inbound_events_employee
  ON inbound_events(target_ai_employee_id, received_at DESC);
```

Notes: Conceptually append-only for the payload; `processing_status`, `picked_up_at`, `completed_at`, `resulting_turn_id`, and `failure_reason` are the only mutable fields. This is the one declared exception to strict append-only, because work-queue state is genuinely operational and not historical fact.

### `agent_timers` (M)

Pending self-prompts and recurring schedules.

```sql
CREATE TABLE agent_timers (
  id                       TEXT PRIMARY KEY,
  ai_employee_id           TEXT NOT NULL,
  scheduled_at             TEXT NOT NULL,
  reason                   TEXT NOT NULL,            -- the agent's note to itself
  originating_turn_id      TEXT NOT NULL,
  inherited_trust_label    TEXT NOT NULL,            -- trust travels
  status                   TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
                             'pending', 'fired', 'cancelled'
                           )),
  fired_at                 TEXT,
  fired_event_id           TEXT,
  created_at               TEXT NOT NULL,
  updated_at               TEXT NOT NULL,
  FOREIGN KEY (ai_employee_id) REFERENCES ai_employees(id),
  FOREIGN KEY (originating_turn_id) REFERENCES turns(id),
  FOREIGN KEY (fired_event_id) REFERENCES inbound_events(id)
);
CREATE INDEX idx_agent_timers_pending
  ON agent_timers(scheduled_at) WHERE status = 'pending';
CREATE INDEX idx_agent_timers_employee
  ON agent_timers(ai_employee_id, status);
```

### `agent_watchers` (M)

Subscriptions to connector resources.

```sql
CREATE TABLE agent_watchers (
  id                              TEXT PRIMARY KEY,
  ai_employee_id                  TEXT NOT NULL,
  resource_uri                    TEXT NOT NULL,    -- e.g. 'jira:FIN-123'
  until_condition                 TEXT,             -- 'resolved', a date, or NULL=forever
  reason                          TEXT NOT NULL,
  originating_turn_id             TEXT NOT NULL,
  inherited_trust_label           TEXT NOT NULL,
  connector_subscription_handle   TEXT,             -- opaque handle from the connector
  status                          TEXT NOT NULL DEFAULT 'active' CHECK (status IN (
                                    'active', 'closed', 'expired', 'errored'
                                  )),
  closed_at                       TEXT,
  created_at                      TEXT NOT NULL,
  updated_at                      TEXT NOT NULL,
  FOREIGN KEY (ai_employee_id) REFERENCES ai_employees(id),
  FOREIGN KEY (originating_turn_id) REFERENCES turns(id)
);
CREATE INDEX idx_agent_watchers_active_employee
  ON agent_watchers(ai_employee_id) WHERE status = 'active';
CREATE INDEX idx_agent_watchers_resource
  ON agent_watchers(resource_uri);
```

---

## 10. Group 6 — Turns and Model Use

### `turns` (M while running; `current_status` cached)

Anchors `run_id`. One row per turn.

```sql
CREATE TABLE turns (
  id                      TEXT PRIMARY KEY,         -- the run_id
  ai_employee_id          TEXT NOT NULL,
  conversation_id         TEXT,
  triggering_event_id     TEXT NOT NULL,
  parent_turn_id          TEXT,                     -- for delegate sub-turns
  current_status          TEXT NOT NULL DEFAULT 'running' CHECK (current_status IN (
                            'running', 'suspended', 'completed', 'failed', 'refused'
                          )),
  suspension_reason       TEXT,                     -- e.g. 'awaiting_approval'
  started_at              TEXT NOT NULL,
  ended_at                TEXT,
  FOREIGN KEY (ai_employee_id) REFERENCES ai_employees(id),
  FOREIGN KEY (conversation_id) REFERENCES conversations(id),
  FOREIGN KEY (triggering_event_id) REFERENCES inbound_events(id),
  FOREIGN KEY (parent_turn_id) REFERENCES turns(id)
);
CREATE INDEX idx_turns_employee_started
  ON turns(ai_employee_id, started_at DESC);
CREATE INDEX idx_turns_active
  ON turns(current_status) WHERE current_status IN ('running', 'suspended');
```

### `turns_status_log` (A)

Status transitions for a turn.

```sql
CREATE TABLE turns_status_log (
  id          TEXT PRIMARY KEY,
  turn_id     TEXT NOT NULL,
  from_status TEXT,
  to_status   TEXT NOT NULL,
  reason      TEXT,
  occurred_at TEXT NOT NULL,
  FOREIGN KEY (turn_id) REFERENCES turns(id)
);
CREATE INDEX idx_turns_status_log_turn
  ON turns_status_log(turn_id, occurred_at);
```

### `model_invocations` (A)

Per-LLM-call record. One turn → 1+ rows.

```sql
CREATE TABLE model_invocations (
  id                      TEXT PRIMARY KEY,
  turn_id                 TEXT NOT NULL,
  sequence_in_turn        INTEGER NOT NULL,         -- 1, 2, 3, ...
  provider                TEXT NOT NULL,            -- 'anthropic', 'openai', 'local'
  model_id                TEXT NOT NULL,
  request_messages_json   TEXT NOT NULL,
  request_tools_json      TEXT,
  response_json           TEXT NOT NULL,
  input_tokens            INTEGER,
  output_tokens           INTEGER,
  cost_usd_micros         INTEGER,                  -- cost in micro-USD (1/1,000,000)
  latency_ms              INTEGER,
  error_text              TEXT,
  invoked_at              TEXT NOT NULL,
  UNIQUE (turn_id, sequence_in_turn),
  FOREIGN KEY (turn_id) REFERENCES turns(id)
);
CREATE INDEX idx_model_invocations_turn
  ON model_invocations(turn_id, sequence_in_turn);
```

Notes: Per-turn aggregates (total tokens, total cost, number of calls) are **derived** via SUM/COUNT over this table; never stored on `turns`.

---

## 11. Group 7 — Work in Flight

### `tasks` (M; `current_status` cached)

Structured work items.

```sql
CREATE TABLE tasks (
  id                       TEXT PRIMARY KEY,
  title                    TEXT NOT NULL,
  description              TEXT,
  owner_principal_id       TEXT NOT NULL,
  source_conversation_id   TEXT,
  source_turn_id           TEXT,
  current_status           TEXT NOT NULL DEFAULT 'open' CHECK (current_status IN (
                             'open', 'in_progress', 'blocked', 'done', 'cancelled'
                           )),
  outcome                  TEXT,                    -- filled when current_status='done'
  due_at                   TEXT,
  created_at               TEXT NOT NULL,
  updated_at               TEXT NOT NULL,
  FOREIGN KEY (owner_principal_id) REFERENCES principals(id),
  FOREIGN KEY (source_conversation_id) REFERENCES conversations(id),
  FOREIGN KEY (source_turn_id) REFERENCES turns(id)
);
CREATE INDEX idx_tasks_owner_status ON tasks(owner_principal_id, current_status);
```

### `tasks_status_log` (A)

```sql
CREATE TABLE tasks_status_log (
  id                  TEXT PRIMARY KEY,
  task_id             TEXT NOT NULL,
  from_status         TEXT,
  to_status           TEXT NOT NULL,
  actor_principal_id  TEXT NOT NULL,
  reason              TEXT,
  occurred_at         TEXT NOT NULL,
  FOREIGN KEY (task_id) REFERENCES tasks(id),
  FOREIGN KEY (actor_principal_id) REFERENCES principals(id)
);
CREATE INDEX idx_tasks_status_log_task
  ON tasks_status_log(task_id, occurred_at);
```

### `pending_approvals` (M; `current_status` cached)

Staged actions awaiting owner approval.

```sql
CREATE TABLE pending_approvals (
  id                              TEXT PRIMARY KEY,
  ai_employee_id                  TEXT NOT NULL,
  originating_turn_id             TEXT NOT NULL,
  proposed_action                 TEXT NOT NULL,    -- one of the 14 action types
  proposed_action_params_json     TEXT NOT NULL,
  drafted_body                    TEXT,             -- e.g. drafted email body
  trust_label                     TEXT NOT NULL,
  requesting_principal_id         TEXT NOT NULL,
  requires_approver_principal_id  TEXT NOT NULL,
  current_status                  TEXT NOT NULL DEFAULT 'open' CHECK (current_status IN (
                                    'open', 'approved', 'rejected',
                                    'edited_and_approved', 'expired'
                                  )),
  resolution_event_id             TEXT,             -- the resolving inbound_event
  resolution_text                 TEXT,             -- approver's note or edited body
  resolved_at                     TEXT,
  expires_at                      TEXT,
  created_at                      TEXT NOT NULL,
  FOREIGN KEY (ai_employee_id) REFERENCES ai_employees(id),
  FOREIGN KEY (originating_turn_id) REFERENCES turns(id),
  FOREIGN KEY (requesting_principal_id) REFERENCES principals(id),
  FOREIGN KEY (requires_approver_principal_id) REFERENCES principals(id),
  FOREIGN KEY (resolution_event_id) REFERENCES inbound_events(id)
);
CREATE INDEX idx_pending_approvals_approver_open
  ON pending_approvals(requires_approver_principal_id) WHERE current_status = 'open';
CREATE INDEX idx_pending_approvals_turn
  ON pending_approvals(originating_turn_id);
```

### `pending_approvals_status_log` (A)

```sql
CREATE TABLE pending_approvals_status_log (
  id                    TEXT PRIMARY KEY,
  pending_approval_id   TEXT NOT NULL,
  from_status           TEXT,
  to_status             TEXT NOT NULL,
  actor_principal_id    TEXT,                       -- NULL for expiry
  reason                TEXT,
  occurred_at           TEXT NOT NULL,
  FOREIGN KEY (pending_approval_id) REFERENCES pending_approvals(id),
  FOREIGN KEY (actor_principal_id) REFERENCES principals(id)
);
```

### `external_intake_items` (M)

`external_verified` sender requests awaiting commander adoption.

```sql
CREATE TABLE external_intake_items (
  id                              TEXT PRIMARY KEY,
  ai_employee_id                  TEXT NOT NULL,
  external_sender_principal_id    TEXT NOT NULL,
  inbound_event_id                TEXT NOT NULL,
  summary                         TEXT,             -- agent's triage summary
  current_status                  TEXT NOT NULL DEFAULT 'awaiting_adoption' CHECK (current_status IN (
                                    'awaiting_adoption', 'adopted', 'rejected', 'expired'
                                  )),
  adopting_principal_id           TEXT,
  adoption_event_id               TEXT,
  resolved_at                     TEXT,
  expires_at                      TEXT,
  created_at                      TEXT NOT NULL,
  FOREIGN KEY (ai_employee_id) REFERENCES ai_employees(id),
  FOREIGN KEY (external_sender_principal_id) REFERENCES principals(id),
  FOREIGN KEY (inbound_event_id) REFERENCES inbound_events(id),
  FOREIGN KEY (adopting_principal_id) REFERENCES principals(id),
  FOREIGN KEY (adoption_event_id) REFERENCES inbound_events(id)
);
CREATE INDEX idx_external_intake_employee_status
  ON external_intake_items(ai_employee_id, current_status);
```

### `quarantined_items` (M)

Items flagged as `external-unverified` or `untrusted-content` — visible to the owner, never acted on by the agent.

```sql
CREATE TABLE quarantined_items (
  id                          TEXT PRIMARY KEY,
  ai_employee_id              TEXT NOT NULL,
  inbound_event_id            TEXT NOT NULL,
  trust_label                 TEXT NOT NULL,
  reason                      TEXT NOT NULL,        -- e.g. 'unverified sender'
  current_status              TEXT NOT NULL DEFAULT 'open' CHECK (current_status IN (
                                'open', 'reviewed', 'summarized', 'expired'
                              )),
  reviewed_by_principal_id    TEXT,
  expires_at                  TEXT,                 -- per SECURITY_SPEC §12 OD-5 (30 days default)
  created_at                  TEXT NOT NULL,
  FOREIGN KEY (ai_employee_id) REFERENCES ai_employees(id),
  FOREIGN KEY (inbound_event_id) REFERENCES inbound_events(id),
  FOREIGN KEY (reviewed_by_principal_id) REFERENCES principals(id)
);
CREATE INDEX idx_quarantined_employee_open
  ON quarantined_items(ai_employee_id) WHERE current_status = 'open';
```

---

## 12. Group 8 — Knowledge

Knowledge in MVP is **file-first**. The DB catalogs documents; text lives on disk.

### File: `memory/<agent_handle>/journal.md`

Not a table. Created when an agent is hired. Append-only markdown log.

Format for each `remember` action:

```markdown
## 2026-05-30T15:04:12Z — fact
Acme Corp uses NET-60 payment terms.
(source: turn pg_8f31, conversation #482)
```

**Recall (MVP):** read last ~8 KB of `journal.md` into the turn context; if the trigger payload has keywords, grep the journal for matching lines. No vector search.

### `ingested_documents` (M)

Catalog row per ingested document. Full text is in `docs/<id>.txt`, not in the DB.

```sql
CREATE TABLE ingested_documents (
  id                        TEXT PRIMARY KEY,
  title                     TEXT NOT NULL,
  source_uri                TEXT,
  mime                      TEXT NOT NULL,
  blob_sha256               TEXT NOT NULL,
  text_path                 TEXT NOT NULL,           -- relative path, e.g. 'docs/01J....txt'
  size_bytes                INTEGER NOT NULL,      -- cache (blob size)
  ingested_by_principal_id  TEXT,
  metadata_json             TEXT,
  ingested_at               TEXT NOT NULL,
  updated_at                TEXT NOT NULL,
  FOREIGN KEY (ingested_by_principal_id) REFERENCES principals(id)
);
CREATE INDEX idx_documents_sha256 ON ingested_documents(blob_sha256);
```

**Recall (MVP):** for documents the agent may read (via `document_access_grants`), grep `docs/*.txt` for keywords from the turn, or include whole file if under a size cap (~32 KB). No chunking, no embeddings.

### Deferred post-MVP

| Feature | When |
|---|---|
| `document_chunks` table | Docs too large to grep whole-file |
| Vector / FTS index | Grep too slow at scale |
| `ai_employee_memory_entries` DB table | Only if file journals need structured query — unlikely; files are the source of truth |

---

## 13. Group 9 — The Action Record

### `agent_action_log` (A; many fields frozen-at-write)

The single source of truth for every gated action. Backs auditor, Pulse, and diagnostics views.

```sql
CREATE TABLE agent_action_log (
  id                              TEXT PRIMARY KEY,
  turn_id                         TEXT NOT NULL,

  -- The four identities (INTEGRATION_WOFKLOW §6) — FROZEN AT WRITE
  technical_actor                 TEXT NOT NULL,    -- e.g. 'pidgin-jira-connector'
  virtual_actor_ai_employee_id    TEXT NOT NULL,
  virtual_actor_display_name      TEXT NOT NULL,    -- frozen
  virtual_actor_role              TEXT NOT NULL,    -- frozen
  requester_principal_id          TEXT NOT NULL,
  requester_display_name          TEXT NOT NULL,    -- frozen
  approver                        TEXT,             -- e.g. 'auto-policy:low-risk' or principal id

  -- The security extension (SECURITY_SPEC §8)
  trust_label                     TEXT NOT NULL,
  policy_decision                 TEXT NOT NULL CHECK (policy_decision IN (
                                    'accepted_as_instruction', 'routed_to_inbox',
                                    'quarantined', 'auto_approved',
                                    'awaiting_human_approval',
                                    'refused_by_policy', 'blocked'
                                  )),

  -- The action
  action_type                     TEXT NOT NULL,    -- one of the 14 actions
  action_params_json              TEXT NOT NULL,
  target_system                   TEXT,             -- e.g. 'jira', 'slack', 'pidgin'
  target_resource                 TEXT,             -- e.g. 'FIN-123'

  -- The result
  outcome                         TEXT NOT NULL CHECK (outcome IN (
                                    'executed', 'staged', 'refused', 'failed'
                                  )),
  outcome_detail_json             TEXT,
  model_invocation_id             TEXT,             -- LLM call that requested this action

  occurred_at                     TEXT NOT NULL,

  FOREIGN KEY (turn_id) REFERENCES turns(id),
  FOREIGN KEY (virtual_actor_ai_employee_id) REFERENCES ai_employees(id),
  FOREIGN KEY (requester_principal_id) REFERENCES principals(id),
  FOREIGN KEY (model_invocation_id) REFERENCES model_invocations(id)
);
CREATE INDEX idx_action_log_turn
  ON agent_action_log(turn_id, occurred_at);
CREATE INDEX idx_action_log_employee_time
  ON agent_action_log(virtual_actor_ai_employee_id, occurred_at DESC);
CREATE INDEX idx_action_log_outcome_time
  ON agent_action_log(outcome, occurred_at DESC);
CREATE INDEX idx_action_log_target
  ON agent_action_log(target_system, target_resource);
CREATE INDEX idx_action_log_policy_decision
  ON agent_action_log(policy_decision, occurred_at DESC);
```

Notes: This is the single most important table for audit, security review, and product surfaces (Pulse, diagnostics). All `*_display_name` and `virtual_actor_role` columns are **frozen at write** — once inserted, never updated, even if the source entity is renamed or deleted.

---

## 14. Caches and Frozen-at-Write Fields

### 14.1 Cached columns (recomputable)

| Table | Column | Source of truth | Rebuild rule |
|---|---|---|---|
| `ai_employees` | `current_status` | latest `ai_employees_status_log.to_status` | `SELECT to_status ORDER BY occurred_at DESC LIMIT 1` |
| `tasks` | `current_status` | latest `tasks_status_log.to_status` | same pattern |
| `pending_approvals` | `current_status` | latest `pending_approvals_status_log.to_status` | same pattern |
| `turns` | `current_status` | latest `turns_status_log.to_status` | same pattern |
| `ai_employee_recipe_snapshots` | `bundle_sha256` | sha256 of `bundle_json` | `SHA256(bundle_json)` |
| `ingested_documents` | `size_bytes` | file on disk | `os.stat(blobs/<sha256>).size` |

### 14.2 Frozen-at-write columns (audit immutability)

| Table | Column |
|---|---|
| `messages` | `sender_display_name` |
| `agent_action_log` | `virtual_actor_display_name`, `virtual_actor_role`, `requester_display_name` |

### 14.3 Explicitly NOT stored (derived on read)

| Concept | How to compute |
|---|---|
| `conversations.last_activity_at` | `MAX(messages.created_at)` for the conversation |
| `ai_employees.resolved_permission_profile` | merge of `recipe_snapshot.bundle_json.permissions` + `workspace.settings_json.overrides` + `ai_employees.permission_overrides_json` |
| `ai_employees.resolved_system_prompt` | §7.2 merge of snapshot `system_prompt_template` + `hire_customization_json` |
| `turns.total_input_tokens` etc. | `SUM(model_invocations.input_tokens)` for the turn |
| `turns.action_count` | `COUNT(agent_action_log)` for the turn |
| `ai_employees.pending_approval_count` | `COUNT(pending_approvals WHERE ai_employee_id=? AND current_status='open')` |

If profiling later shows any of these are expensive enough to need caching, we add a clearly-marked cache column with a rebuild rule. Until then, derive.

---

## 15. Schema Migrations

- One migration history per physical DB file (per-workspace SQLite). Tracked in `schema_migrations`.
- Migrations are forward-only; rollbacks happen by creating a new forward migration.
- Each migration is a numbered SQL file with a checksum recorded in `schema_migrations.checksum`.
- On every `open_workspace`, the runtime checks for pending migrations and applies them inside a transaction. Failure aborts the open.
- The same migration files apply to every workspace's DB; per-workspace customization lives in `workspace.settings_json`, not in schema variations.

### 15.1 Migration ledger

| Version | File | Change |
|---|---|---|
| `001_initial` | `migrations/001_initial.sql` | 26 tables — initial schema |
| `002_hire_customization` | `migrations/002_hire_customization.sql` | Add `ai_employees.hire_customization_json TEXT` (nullable) |

`002_hire_customization.sql`:

```sql
ALTER TABLE ai_employees ADD COLUMN hire_customization_json TEXT;
```

Existing rows: column is `NULL` until hire flow or profile edit populates it. Hire UX file layout (`role-templates/`, `hr-assist/`, `audit/`) requires **no migration** — directories are created on first use.

---

## 16. Open Decisions

| # | Decision | Notes |
|---|----------|-------|
| 1 | Memory journal tail size for recall | Default ~8 KB; tunable per recipe |
| 2 | Document whole-file size cap for recall | Default ~32 KB; larger docs require grep |
| 3 | Quarantine retention | Default 30 days per SECURITY_SPEC OD-5 |
| 4 | Pending approval expiry default | Recommendation: 14 days |
| 5 | External intake expiry default | Recommendation: 7 days |
| 6 | Recipe snapshot retention on offboarding | Recommendation: keep forever (audit) |
| 7 | Search upgrade path | grep → SQLite FTS on files → vectors (post-MVP) |

---

## Cross-References

- [PRODUCT_SPEC.md](PRODUCT_SPEC.md) — Product vision, entities, recipe model
- [SECURITY_SPEC.md](SECURITY_SPEC.md) — Principals, trust labels, policy decisions, attribution model
- [INTEGRATION_WOFKLOW.md](INTEGRATION_WOFKLOW.md) — Connector model, the four-identity attribution
- [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) — Triggers, actions, turn lifecycle, gate semantics, prompt construction
- [RECIPES_SPEC.md](RECIPES_SPEC.md) — Bundled role recipe fields, `default_job_requirements`, prompt template
- [HIRE_UX.md](HIRE_UX.md) — Hire wizard UX, template vocabulary, HR assist surfaces
- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) — Phase 1B hire UX tasks and API routes
- [TECH_STACK_SPEC.md](TECH_STACK_SPEC.md) — Python stack, MVP tooling, what we deliberately omit
