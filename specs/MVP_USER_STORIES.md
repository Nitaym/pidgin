# MVP User Stories

Acceptance criteria for the first shippable slice. Phase 0 covers foundation; Phase 1 covers hire, templates, and first turn.

**Hire UX vocabulary and flows:** [HIRE_UX.md](HIRE_UX.md) (operator-facing labels; internal code may still say “recipe”).

---

## US-1: Create workspace

**As** an operator  
**I want** to create a password-protected workspace directory  
**So that** agent data is isolated on disk

**Phase:** 0

**Acceptance**
- React UI: create workspace form with name + slug (or `POST /api/workspace`)
- Creates workspace directory with `auth.json` (bcrypt hash only), `memory/`, `docs/`, `blobs/`
- Registers workspace in registry
- Applies DB migration and inserts `workspace` row

---

## US-2: Open workspace

**As** an operator  
**I want** to unlock a workspace with its password in the admin UI  
**So that** diagnostics and commands can access DB and files

**Phase:** 0

**Acceptance**
- Wrong password → clear error on unlock form, no diagnostics shown
- Correct password → session unlocked; workspace dashboard shows events/turns/audit

---

## US-3: Process inbound event (stub)

**As** the runtime  
**I want** to dequeue pending `inbound_events` and create a turn  
**So that** agent work is traceable

**Phase:** 0

**Acceptance**
- Diagnostics: **Inject test event** then **Run once** (or `POST /api/.../inject-event` + `run-once`)
- Event moves `pending` → `dispatching` → `done` — visible in Events table
- A `turns` row and `agent_action_log` row are created (stub read action) — visible in Turns + Audit

---

## US-4: Policy gate

**As** the system  
**I want** every proposed action checked against permissions and trust  
**So that** unsafe actions are refused or staged

**Phase:** post-MVP (skeleton only in MVP)

**Acceptance**
- Blocked actions → `refused_by_policy`
- Approval-required actions → `awaiting_human_approval` / staged
- Internal trusted actions → `accepted_as_instruction`

---

## US-5: Agent memory (file-based)

**As** an agent  
**I want** to append to `memory/<handle>/journal.md` and recall via tail/grep  
**So that** long-term notes persist without vectors

**Phase:** 0

**Acceptance**
- `remember` appends timestamped markdown section
- `recall_tail` returns last N lines

---

## US-6: Hire from role template with customizable brief

**As** a workspace operator  
**I want** to pick a role template, edit job requirements and ideal candidate profile (including my own take), and hire  
**So that** the agent matches our company rather than a generic default

**Phase:** 1B

**Acceptance**
- **Hire a role** flow never uses the word “recipe” in UI (see [HIRE_UX.md](HIRE_UX.md))
- Step 1 lists **Pidgin role templates** (minimum: Support Agent) and **Your role templates**
- Steps 2–3 pre-fill **Job requirements** (mission, responsibilities, out of scope) and **Ideal candidate profile** (tone, decision framework, escalation rules) from template defaults
- Operator can edit all pre-filled fields and add **Your take** freeform text
- Step 4: agent display name, handle, manager (default: logged-in user)
- Step 5: review summary in operator language; **Hire and continue** creates employee in `draft`, immutable template snapshot, default rooms, memory dir
- Operator customization (job requirements, ideal candidate, your take) persisted on the employee record separately from the snapshot
- Duplicate handle → clear error; MVP allows one Support Agent instance unless product rule changes
- Agent appears on Team with status badge

**API path (illustrative):** `GET .../role-templates`, `POST .../hire` with `template_id` + `customization` + identity fields

---

## US-7: Pidgin HR assist while defining the role

**As** a workspace operator  
**I want** to chat with Pidgin while editing job requirements and ideal candidate profile  
**So that** I get help curating and optimizing the brief even without an HR agent hired

**Phase:** 1C (may ship stub LLM after US-6 form UI)

**Acceptance**
- **Discuss with Pidgin** chat panel on hire wizard steps 2–3, agent profile edit, and workspace template editor
- Assist available without any HR agent hired (built-in Pidgin coach, not an `ai_employees` row)
- Operator can send messages; assist replies with clarifying questions and suggested copy
- **Apply to form** applies a suggestion to the targeted field(s); **Append to your take** adds text without overwriting other fields
- Chat history persisted per hire session, agent, or template edit context — survives page refresh
- If assist backend unavailable, form save and hire still succeed; UI shows degraded state, not a hard block

**Deferred**
- Routing assist to a hired HR agent instead of Pidgin default

---

## US-8: Your role templates (create, edit, version, persist)

**As** a workspace operator  
**I want** to create and save my own role templates as versioned files and edit them later  
**So that** I can reuse and evolve our company’s hiring standards

**Phase:** 1B2

**Acceptance**
- **Create blank template** opens editor with empty job requirements and ideal candidate sections
- **Duplicate** a Pidgin role template into **Your role templates** (Pidgin original unchanged)
- Workspace templates stored as **text files** under workspace `role-templates/` — **not in SQLite** (see [HIRE_UX.md](HIRE_UX.md) §2.1)
- Saving under the **same template name** promotes a **new version** (`v1`, `v2`, …); prior version files remain on disk
- UI shows current (latest) version; operator can view version history
- All creates and edits persist to disk; navigating away does not lose unsaved work (auto-save or explicit save with warning)
- Template list shows name, current version, last updated, optional “used for N hires”
- Delete workspace template (latest or entire slug folder) with confirmation; Pidgin templates cannot be deleted
- Saved template appears in hire wizard step 1

**Architect handoff:** file layout, manifest schema, `GET/POST/PATCH .../role-templates` mapping to files

---

## US-9: Edit agent brief after hire

**As** a workspace operator  
**I want** to edit job requirements, ideal candidate profile, and your take on a hired agent  
**So that** the agent can improve as our needs change

**Phase:** 1B3

**Acceptance**
- Agent profile exposes editable sections for job requirements, ideal candidate profile, and your take
- **Save** persists changes to the employee record (not the immutable hire snapshot)
- Each save writes an audit entry (who, when, what changed — field-level or diff summary)
- HR assist panel available on profile edit (US-7)
- Resolved agent behavior uses updated brief on subsequent turns (once runtime reads customization)

---

## US-10: Create template from agent

**As** a workspace operator  
**I want** to save a hired agent’s brief as a new role template  
**So that** I can hire similar agents or share our tuned definition

**Phase:** 1B2

**Acceptance**
- Agent profile → **Create template from this agent** opens template editor pre-filled from current brief + access summary
- Does not copy agent identity (display name, handle, manager, lifecycle status)
- Operator names the new template and saves to **Your role templates**
- Saved template is immediately usable in hire wizard step 1 (starts at workspace `v1`)
- Lineage note stored in template manifest: derived from agent handle and source template name/version

---

## US-11: Complete interview before activation

**As** a workspace operator  
**I want** to run interview scenarios from the role template before activating the agent  
**So that** I only promote agents I trust

**Phase:** 1D

**Acceptance**
- Starting interview sets status `interviewing`
- Scenarios defined on template (when [RECIPES_SPEC.md](RECIPES_SPEC.md) extended); Support Agent: minimum 2 scenarios
- Each scenario: brief + interaction surface; completion recorded
- Pass all → status `onboarding`; fail allows retry
- Optional operator skip with explicit confirm + audit entry (dev escape hatch)

**Depends on:** `INTERVIEW_SPEC.md`, architect scenario schema

---

## US-12: Onboard in shadow mode and activate

**As** a workspace operator  
**I want** an onboarding checklist and explicit activation  
**So that** agents ramp safely before full access

**Phase:** 1E

**Acceptance**
- Onboarding checklist from template; items completable manually in MVP
- Agent visible in assigned rooms during onboarding; risky actions labeled or staged in UI
- **Activate agent** → status `active`; Team page enables primary chat CTA

---

## Deferred (not active acceptance)

- Real LLM turn with full tool calls (Phase 2)
- Human approval inbox UI (Phase 3)
- Hired HR agent replaces Pidgin assist (post-MVP)
- Permission override UI on hire/profile (post-MVP; read-only summary in MVP)
- Hierarchy recipe picker on workspace create (silent SaaS defaults for now)
- Custom roles from absolute scratch without template structure (v0.2)
