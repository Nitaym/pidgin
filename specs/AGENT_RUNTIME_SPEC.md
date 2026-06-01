# Pidgin Agent Runtime Spec

## Summary

```text
An AI employee in Pidgin is woken by one of 8 triggers, runs one or more turns, and emits any of 14 actions during each turn. Every action goes through a single policy gate before it can produce a side effect. Structured state lives in the per-workspace SQLite DB; agent memory and document text live in companion files on disk.
```

The short product line:

```text
An AI employee is a small vocabulary - 8 ways to be woken, 14 things to do, one gate. Everything else is composition.
```

> **Scope:** The behavioral primitives of an AI employee and the runtime that hosts them. Defines what triggers a turn, what an agent can do during a turn, what context it receives, and where the policy gate lives. Pairs with [SCHEMA_SPEC.md](SCHEMA_SPEC.md) which defines how this state is persisted.
>
> **Out of scope:** The recipe authoring/marketplace flow, the interview and onboarding scenario harness, the reviewer agent, the diagnostics UI specifics, LLM-provider-level concerns (model selection, fail-over, cost accounting), vector/semantic search. See [TECH_STACK_SPEC.md](TECH_STACK_SPEC.md) for stack choices.

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [The Trigger Model](#2-the-trigger-model)
3. [The Action Model](#3-the-action-model)
4. [Sense of Time](#4-sense-of-time)
5. [Memory and Knowledge Scopes](#5-memory-and-knowledge-scopes)
6. [Self-Prompting](#6-self-prompting)
7. [Turn Lifecycle](#7-turn-lifecycle)
8. [The Policy Gate](#8-the-policy-gate)
9. [MVP Runtime Architecture](#9-mvp-runtime-architecture)
10. [Diagnostics and Debug Export](#10-diagnostics-and-debug-export)
11. [Out of Scope](#11-out-of-scope)
12. [Open Decisions](#12-open-decisions)

---

## 1. Purpose

[PRODUCT_SPEC.md](PRODUCT_SPEC.md), [SECURITY_SPEC.md](SECURITY_SPEC.md), and [INTEGRATION_WOFKLOW.md](INTEGRATION_WOFKLOW.md) collectively define **what** an AI employee is and the guarantees the system must provide around its actions. This spec defines the small set of primitives an AI employee actually **uses** — the trigger and action vocabulary that everything else (interviews, onboarding, conversations, tasks, Pulse) composes from.

The design goal is to keep this vocabulary small. A human employee operates with a similarly small set of primitives: react to direct address, scan ambient activity, remember things, plan future check-ins, ask permission for risky actions, hand off when blocked. The runtime mirrors that vocabulary directly.

---

## 2. The Trigger Model

A **turn** (one wakeup → think → do → sleep cycle) starts from exactly one of these eight triggers. Nothing else can start a turn.

| # | Trigger | Human analogy | Materialized as |
|---|---|---|---|
| 1 | **Direct address** | Someone DMs or @mentions you | `inbound_events` row from chat/email connector |
| 2 | **Channel activity** | You overhear something in a room you sit in | `inbound_events` row from room subscription (opt-in per room) |
| 3 | **Inbound from outside** | Email or external chat arrives | `inbound_events` row from email/external connector |
| 4 | **Timer** | A scheduled obligation comes due | `agent_timers` firing → `inbound_events` row |
| 5 | **Watcher fires** | Something you were keeping an eye on changed | `agent_watchers` firing → `inbound_events` row |
| 6 | **Self-prompt** | You remember a follow-up you owed yourself | Same mechanism as (4), set by the agent itself |
| 7 | **Peer delegation** | A colleague asks you for help | `inbound_events` row created by another agent's `delegate` action |
| 8 | **Approval response** | Your owner got back to you on something you staged | `pending_approvals` resolution → `inbound_events` row resuming the original `run_id` |

### 2.1 Properties of triggers

1. **Every trigger materializes as a row in `inbound_events`.** The runtime polls one queue, not eight; trigger type is a field on the row.
2. **Triggers 4–6 are time-based.** They are how an agent acts without being externally prompted. See Section 6.
3. **Trigger 8 resumes a prior turn** rather than starting a new one. This is what makes approvals feel like the agent waiting on an answer rather than starting fresh.
4. **Triggers 1 and 2 are different.** Direct address obligates a response; channel activity invites attention. The agent decides whether to act on (2). Channel-activity subscription is off by default per room and must be opted-in.
5. **Trigger 7 carries the original requester chain.** Per [SECURITY_SPEC §10](SECURITY_SPEC.md), delegation does not launder authority.

---

## 3. The Action Model

During a turn, an agent may emit any combination of these 14 actions. The runtime exposes exactly these; anything else is composed from them.

| # | Action | Effect | Default approval bucket |
|---|---|---|---|
| 1 | **say** | Reply on the channel the turn started on (or stay silent) | always allowed |
| 2 | **post** | Send a message on a *different* channel | `can_write` |
| 3 | **read** | Pull from a connector | `can_read` |
| 4 | **draft** | Compose a connector-side artifact without publishing | `can_write` (draft only) |
| 5 | **execute** | Publish or mutate something in a connector | `requires_approval` or `can_write` |
| 6 | **open_task** | Create a structured task with owner/status | always allowed |
| 7 | **remember** | Write to the agent's memory scope | always allowed |
| 8 | **recall** | Read from memory + indexed company context | always allowed |
| 9 | **schedule_self** | Set a timer for a future wakeup (triggers 4 or 6) | always allowed |
| 10 | **watch** | Subscribe to a connector resource (trigger 5) | subject to `can_read` |
| 11 | **delegate** | Call another agent (their trigger 7) | depends on hierarchy recipe |
| 12 | **request_approval** | Stage an action for the owner even if it would be allowed | always allowed |
| 13 | **escalate** | Hand work back to the human owner/manager with context | always allowed |
| 14 | **close** | Mark a Task or Conversation done with an outcome | always allowed |

### 3.1 Why draft and execute are separated

The split between **draft** (4) and **execute** (5) is load-bearing. Most of the "approve before send" behavior in [SECURITY_SPEC §7](SECURITY_SPEC.md) and [INTEGRATION_WOFKLOW §4.5](INTEGRATION_WOFKLOW.md) is the gate refusing `execute` while permitting `draft`. A drafted email exists as a connector-side resource (or as `pending_approvals.drafted_body`) until a commander explicitly executes it.

### 3.2 Composability

Actions compose to produce the higher-level behaviors described in [PRODUCT_SPEC.md](PRODUCT_SPEC.md):

| Higher-level behavior | Composed from |
|---|---|
| "Investigate" action button | `read` + `recall` + `say` |
| "Draft" action button | `read` + `draft` + `say` |
| "Execute" action button | `read` + (optional `request_approval`) + `execute` + `say` |
| Standup digest | `recall` + `post` |
| Follow-up scheduling | `say` + `schedule_self` |
| Cross-role escalation | `escalate` or `delegate` |
| Pulse query response | `recall` + `say` |

The product surface (action buttons, recipe behaviors, room rules) is implemented as combinations of these 14 primitives.

---

## 4. Sense of Time

LLMs are stateless about time. A model call is a self-contained prompt; the model does not know what time it is, how long ago the last message was, or how old anything in front of it is unless the runtime injects those facts as text.

Without this, agents do dumb things: replying to a 3-day-old thread as if it just arrived; failing to act on a deadline because they don't know whether the date is past or future; waking on a timer without knowing why they set it.

The runtime injects three categories of temporal facts into every turn's context.

### 4.1 Absolute time

A single line near the top of the prompt:

```text
now: 2026-05-29T18:23:04+03:00
```

### 4.2 Elapsed time on referenced entities

Whenever the runtime includes a conversation, task, document, or event in the prompt, it annotates how old each thing is relative to `now`:

```text
Conversation #482 with Dana Levi (started 4 days ago)
  [4 days ago] Dana:   Can you check the PO on invoice 4421?
  [4 days ago] Jane:   Looking into it now.
  [just now]   Dana:   Any update?
```

### 4.3 Pending self-obligations

When a turn runs, the runtime injects the agent's own pending `agent_timers` and `agent_watchers` rows as a glance at the agent's "calendar":

```text
My scheduled wakeups:
  3pm today    - follow up with Dana on PO question (set this morning)
  9am tomorrow - daily inbox summary
  Friday       - check on Acme renewal

Things I'm watching:
  jira:FIN-123 - customer waiting on resolution
```

This is what makes an agent "know when to act": it can see what it has already committed to and reason about whether to schedule, cancel, or wait.

### 4.4 What this is not

The MVP "sense of time" is intentionally minimal. It does not include:

- Timezone-aware calendar arithmetic
- Recurring schedule expressions (`cron`-style)
- Business-hours awareness
- SLA computation
- Deadline projection

Those layer on top later. The MVP primitive is: stamp `now`, annotate ages, show pending obligations.

---

## 5. Memory and Knowledge Scopes

Three scopes. **Conversation state** is in the DB; **agent memory and document text** are files on disk for MVP.

| Scope | Contents | Storage | Writer | Readers |
|---|---|---|---|---|
| **Agent memory** | Facts, decisions, preferences, outcomes | `memory/<handle>/journal.md` | this agent via `remember` | this agent only |
| **Conversation state** | Open threads, last message, who's waiting on what | DB (`conversations`, `messages`) | runtime + this agent | this agent only (per conversation) |
| **Company context** | Ingested documents, workspace directory | DB catalog + `docs/*.txt` files | runtime (ingestion) + admin | agents with `document_access_grants` |

Humans keep notebooks, not SQL tables. Agents do the same for MVP — an append-only journal per agent, greppable and readable in any editor.

### 5.1 Per-agent memory isolation

Each agent has its own `memory/<handle>/` directory. Jane's journal is invisible to Max. Cross-agent context flows only through company documents (with access grants) or explicit `delegate`.

### 5.2 Memory journal format

Each `remember` appends a dated block to `journal.md`:

```markdown
## 2026-05-30T15:04:12Z — fact
Acme Corp uses NET-60 payment terms.
(source: turn pg_8f31)
```

Kinds: `fact`, `decision`, `preference`, `outcome`, `reminder` — tagged in the heading for grep.

### 5.3 Recall (MVP)

The `recall` action:

1. Reads the **tail** of the agent's `journal.md` (default ~8 KB).
2. If the turn has searchable keywords, **greps** the journal for matching lines.
3. For granted documents, **greps** `docs/*.txt` or reads whole file if under size cap (~32 KB).

No embeddings, no vector DB, no chunk tables. Upgrade search on the file layer when volume demands it.

---

## 6. Self-Prompting

This is what turns a chatbot into an employee. Self-prompting is the composition of `schedule_self` (action 9) and `watch` (action 10) with triggers 4 and 5:

```
At end of any turn, the agent MAY emit:
  schedule_self(at=2026-05-30T15:00, reason="follow up with Dana on PO question")
  watch(resource="jira:FIN-123", until=resolved, reason="customer waiting")

Later, when that timer fires or watcher trips:
  Trigger 4 or 5 starts a new turn.
  Context includes the original reason and the elapsed time.
  The agent acts (or chooses to wait further) and may re-schedule.

This is how an agent acts without external prompting.
```

### 6.1 Safety properties enforced by the runtime

1. **Trust label inheritance.** Self-prompts inherit the `trust_label` of the turn that created them (stored on `agent_timers.inherited_trust_label`). A turn triggered by `untrusted-content` cannot escalate itself to `internal-authenticated` via a self-prompt.
2. **Budget.** Each agent has a per-day cap on pending self-prompts (`max_pending_timers`) and on wakeups (`max_wakeups_per_day`). Configurable per recipe; defaults TBD (Open Decision 4). Prevents runaway self-prompting from any source — buggy recipe, prompt injection, infinite-loop logic.
3. **Cancellation.** An agent can cancel its own pending timers (via a corresponding internal action). Cancellation goes through the gate like any other action.

---

## 7. Turn Lifecycle

A turn is the atomic unit of agent work. One trigger → one turn (with optional resumes).

### 7.1 Phases

```
1. Trigger materializes as an inbound_events row (processing_status='pending').
2. Runtime resolves principal and attaches trust_label (see SECURITY_SPEC §3-4).
3. Runtime starts or resumes a turn:
   - New turn: insert into turns, link via inbound_events.resulting_turn_id.
   - Resume:   load turn referenced by inbound_events.resumes_turn_id.
4. Runtime builds context:
   - trigger payload
   - conversation state (if any)
   - agent memory entries (via recall on trigger content)
   - referenced company documents (filtered by document_access_grants)
   - pending self-obligations (agent_timers, agent_watchers)
   - resolved permission profile (recipe + workspace overrides + employee overrides)
   - sense-of-time injection per Section 4
5. Runtime calls the LLM. Full request and response logged as a model_invocations row.
6. The LLM emits 0+ actions. Each goes through the policy gate (Section 8).
7. Accepted actions execute; agent_action_log rows written for every gate decision.
8. If the model wants another iteration (saw a tool result, needs to think more):
   - Loop back to step 5.
9. Turn ends in one of:
   - completed: all actions resolved
   - suspended: one or more pending_approvals open; turn parks until trigger 8
   - failed:    runtime error
   - refused:   gate refused enough actions that nothing meaningful proceeds
```

### 7.2 Concurrency

- **One turn at a time per `(ai_employee_id, conversation_id)`.** Parallel turns across different conversations are fine.
- **Suspended turns hold no in-memory state.** A turn waiting on approval can wait hours or days; state lives entirely in the DB.
- **Crash-resumable.** On runtime startup, any `inbound_events.processing_status = 'pending'` rows are picked up; any `turns.current_status = 'running'` rows are reconciled (timed-out turns marked `failed` and optionally retried).

### 7.3 Sub-turns via delegate

When agent A's turn invokes `delegate` to agent B:

- A new `inbound_events` row is created (trigger 7) addressed to B
- The originating turn's `id` is recorded as `parent_turn_id` on the new event
- A's turn may either wait on the result (suspends, resumes on B's completion event) or fire-and-forget
- Authorization propagates: B sees both `requester=agentA` and the chain back to the original human requester, per [SECURITY_SPEC §10](SECURITY_SPEC.md)

---

## 8. The Policy Gate

Every action the LLM emits is gated before it can produce a side effect. The gate is a pure function:

```
gate(principal, trust_label, ai_employee, action) -> decision

decision in {
  accept,                  // action executes
  stage_as_pending_approval,
  stage_as_external_intake,
  quarantine,
  refuse,                  // policy violation or blocked
}
```

### 8.1 Inputs to the gate

- `principal` — from the originating `inbound_events` row
- `trust_label` — from the originating event
- `ai_employee.invocation_policy` — derived from the recipe + hierarchy (commanders / requesters / external_intake / untrusted, per [SECURITY_SPEC §5](SECURITY_SPEC.md))
- `ai_employee.permission_profile` — resolved (`can_read` / `can_write` / `requires_approval` / `blocked`, per [INTEGRATION_WOFKLOW §4-5](INTEGRATION_WOFKLOW.md))
- `action.type` and `action.params`

### 8.2 Instructions vs. data enforcement

The gate refuses any action whose causal trigger is `untrusted-content` with no commander instruction in the same turn (per [SECURITY_SPEC §6](SECURITY_SPEC.md)). Concretely: a turn whose trigger had `trust_label = untrusted-content`, or a turn that pulled in untrusted content via `read`, cannot have that content originate a `post`/`draft`/`execute` call.

### 8.3 Where the gate lives

The gate runs **outside the LLM**, in runtime code. The LLM never makes the final call about whether a tool fires. This is the single most important enforcement point in the system.

For MVP, the gate is an in-process pure function. The contract is small enough that it can be lifted into its own service later without changing callers.

### 8.4 Audit invariant

**Every gate decision produces an `agent_action_log` row**, regardless of outcome (`executed` / `staged` / `refused` / `failed`). The audit log is the projection of every gate decision the system ever made. There is no "silent refusal." This is what makes the diagnostics view and the Pulse view possible from the same source of truth.

---

## 9. MVP Runtime Architecture

For MVP, the runtime is a single process running locally, capable of offline operation.

### 9.1 Process model

One `pidgind` process containing:

| Component | Role |
|---|---|
| **Scheduler** | Wakes on the soonest `agent_timers.scheduled_at` across loaded workspaces; converts fired timers into `inbound_events` rows |
| **Watcher dispatcher** | Receives connector-side change notifications; converts into `inbound_events` rows |
| **Event dispatcher** | Picks up `inbound_events` rows with `processing_status='pending'`; starts or resumes turns |
| **Turn executor** | Runs the lifecycle of Section 7 |
| **Policy gate** | In-process function called for every action |
| **LLM gateway** | Module behind a single `call(messages, tools, budget) → response` interface; HTTP-backed |
| **Connector layer** | One module per integration (Slack, Email, Jira, Google Workspace, ...) implementing a uniform contract |
| **Diagnostics web server** | Read-only views over the DB |
| **Main web/desktop UI** | The user-facing workspace (rooms, conversations, agents, tasks, Pulse) |

### 9.2 Storage

- **One workspace directory** per tenant: plain `db.sqlite` + `memory/`, `docs/`, `blobs/` text files.
- **Each workspace has its own password.** Caller supplies it at open time; Pidgin verifies against a bcrypt hash in `auth.json` and **never stores the password**. For MVP the operator keeps passwords wherever they like; production injects from K8s secrets / Vault / env.
- **No OS keychain, no Argon2id, no AES credential encryption** in MVP — keep it simple.
- See [SCHEMA_SPEC.md §4](SCHEMA_SPEC.md) for layout and lifecycle commands.

### 9.3 LLM gateway

A single module behind a `call(messages, tools, budget) → response` interface. In MVP it makes direct HTTPS calls to the model provider; in the future it can be extracted to a sidecar service without changing callers.

Responsibilities:

- Provider routing (Anthropic / OpenAI / local model)
- Prompt construction (system prompt + context + tool definitions)
- Response parsing (extract `say` text + tool calls)
- Cost accounting (writes `model_invocations` row per call)
- Budget enforcement (per-workspace, per-agent, per-turn)

### 9.4 Connector layer

Each integration is a module implementing a small uniform contract:

```
read(resource, principal) -> bytes | structured_data
write(resource, payload, principal) -> handle
subscribe(resource, callback) -> watcher_handle
unsubscribe(handle)
metadata() -> { capabilities, rate_limits, ... }
```

All calls go through the policy gate before the connector module is invoked. **Simulated connectors** for interview/onboarding implement the same contract and are substituted at injection time — same Loop 3 code path, different connector implementations.

Implementation details (auth modes, resource URIs, admin API, UI, build order): [CONNECTORS_SPEC.md](CONNECTORS_SPEC.md).

### 9.5 Recipe consumption

The runtime fetches recipe bundles from a **separate marketplace app** at hire time, verifies the bundle's sha256, and stores an immutable snapshot in `ai_employee_recipe_snapshots`. After hire, the runtime never reads the marketplace again for that agent.

Recipe upgrades create new snapshot rows; running agents stay pinned to their hired version until an admin explicitly upgrades them.

### 9.6 Separability promises

The following are kept behind clean module boundaries even though they run in-process for MVP, so they can be lifted out without API changes later:

1. **LLM gateway** — module behind a single interface
2. **Connector layer** — module per integration with a uniform contract
3. **Policy gate** — pure function with a typed contract
4. **Recipe marketplace** — separate app, talks to runtime over HTTP only

---

## 10. Diagnostics and Debug Export

### 10.1 Diagnostics web app

A read-only set of views over the per-workspace DB. Routes:

| Route | Shows |
|---|---|
| `/turns` | List of all turns (filterable by agent, conversation, status, trust label, policy decision) |
| `/turns/<run_id>` | Single-turn timeline: trigger → principal → context → LLM call(s) → action(s) → gate decisions → audit rows |
| `/agents/<id>` | Agent profile: pending timers, watchers, recent turns, resolved permission profile, recipe version |
| `/audit` | Raw `agent_action_log` with filters by trust label, policy decision, action type |
| `/pulse` | Same data, curated for end users (filters / summaries) |

The diagnostics view and the Pulse view read from the same `agent_action_log` and supporting tables. Pulse is the curated/summarized view for end users; diagnostics is the raw view for developers.

### 10.2 File export (flag-controlled, off by default)

When enabled per workspace, every turn flushes a folder as it runs:

```
workspaces/<id>/_debug/
  2026-05-29/
    18-23-04__pg_8f31__jane__followup-on-PO/
      turn.md
      prompt.txt
      response.txt
      gate-decisions.jsonl
      tool-calls.jsonl
      audit.jsonl
      events.jsonl
```

`turn.md` renders the same timeline as the web app's single-turn view, in a format that is:

- Greppable with regular tools
- Pasteable into bug reports
- Loadable as context by AI coding tools
- Readable in any editor

### 10.3 Security trade-off

Debug export creates plaintext files of prompts and responses on disk. For MVP this is consistent with the DB itself being plaintext; the flag remains **off by default**, requires explicit opt-in per workspace, surfaces a clear warning at enable time, and auto-purges after a configurable retention (default 7 days).

When full DB encryption lands post-MVP, an "encrypted debug export" mode can be added that writes the same files encrypted under the workspace key, without breaking the use case for tooling that holds the key.

---

## 11. Out of Scope

Deferred to separate specs:

- Recipe authoring schema and marketplace UX → future `RECIPES_SPEC.md`
- Interview scenario harness and scoring rubric → future `INTERVIEW_SPEC.md`
- Reviewer agent and recipe improvement loop → future `REVIEWER_SPEC.md`
- Pulse query language and summarization rules → future `PULSE_SPEC.md`
- Voice notes, calls, meetings, screen-share (MVP is text only)
- Vector / semantic search over memory and documents
- Multi-machine deployment, high availability, cross-tenant federation
- OS keychain integration and credential encryption at rest (MVP uses external password supply + plaintext connector JSON)
- Authentication protocols (DKIM/DMARC, OAuth, mTLS) → future `SECURITY_PROTOCOLS_SPEC.md`

---

## 12. Open Decisions

| # | Decision | Status |
|---|----------|--------|
| 1 | Language and runtime | **Python 3.12+** — see [TECH_STACK_SPEC.md](TECH_STACK_SPEC.md) |
| 2 | Web framework | **FastAPI** — see TECH_STACK_SPEC |
| 3 | LLM client library | Official `anthropic` + `openai` SDKs |
| 4 | Self-prompt budget defaults | Recommendation: 50 pending timers, 100 wakeups/day |
| 5 | DB encryption (post-MVP) | SQLCipher when multi-tenant |
| 6 | Channel activity default (trigger 2) | Off-by-default per room |
| 7 | Debug export retention | 7 days default |
| 8 | Turn failure retry policy | Auto-retry network errors once |
| 9 | Memory recall tail size | ~8 KB journal tail; grep for keywords |
| 10 | Document recall size cap | ~32 KB whole-file; else grep |

---

## Cross-References

- [PRODUCT_SPEC.md](PRODUCT_SPEC.md) — Product vision, entities, recipe model, user flows
- [SECURITY_SPEC.md](SECURITY_SPEC.md) — Principals, trust labels, invocation policy, gate semantics
- [INTEGRATION_WOFKLOW.md](INTEGRATION_WOFKLOW.md) — Connector model, attribution, permission buckets
- [SCHEMA_SPEC.md](SCHEMA_SPEC.md) — Per-workspace DB schema backing this runtime
- [TECH_STACK_SPEC.md](TECH_STACK_SPEC.md) — Language, libraries, and MVP tooling choices
