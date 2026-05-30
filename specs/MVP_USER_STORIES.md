# MVP User Stories

Acceptance criteria for the first shippable slice. Phase 0 covers foundation; Phase 1 covers hire + first turn.

## US-1: Create workspace

**As** an operator  
**I want** to create a password-protected workspace directory  
**So that** agent data is isolated on disk

**Acceptance**
- React UI at `/`: create workspace form with name + password (or `POST /api/workspaces`)
- Creates `~/.pidgin/workspaces/<ulid>/` with `auth.json` (bcrypt hash only), `memory/`, `docs/`, `blobs/`
- Registers workspace in `workspaces_registry.json`
- Applies DB migration and inserts `workspace` row

## US-2: Open workspace

**As** an operator  
**I want** to unlock a workspace with its password in the admin UI  
**So that** diagnostics and commands can access DB and files

**Acceptance**
- Wrong password → clear error on unlock form, no diagnostics shown
- Correct password → session unlocked; workspace dashboard shows events/turns/audit

## US-3: Process inbound event (stub)

**As** the runtime  
**I want** to dequeue pending `inbound_events` and create a turn  
**So that** agent work is traceable

**Acceptance**
- Admin: **Inject test event** then **Run once** (or `POST /api/workspaces/{id}/inject-event` + `run-once`)
- Event moves `pending` → `dispatching` → `done` — visible in admin Events table
- A `turns` row and `agent_action_log` row are created (stub read action) — visible in Turns + Audit

## US-4: Policy gate

**As** the system  
**I want** every proposed action checked against permissions and trust  
**So that** unsafe actions are refused or staged

**Acceptance**
- Blocked actions → `refused_by_policy`
- Approval-required actions → `awaiting_human_approval` / staged
- Internal trusted actions → `accepted_as_instruction`

## US-5: Agent memory (file-based)

**As** an agent  
**I want** to append to `memory/<handle>/journal.md` and recall via tail/grep  
**So that** long-term notes persist without vectors

**Acceptance**
- `remember` appends timestamped markdown section
- `recall_tail` returns last N lines

## Deferred to Phase 1

- Hire from `recipes/support-agent-v0.1.json`
- Real LLM turn with tool calls
- Pidgin-native chat connector
- Human approval inbox UI
