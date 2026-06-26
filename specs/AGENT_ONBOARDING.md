# Agent Onboarding Documentation

> **Scope:** How every hired agent learns about the company before doing productive work, where
> that knowledge lives, and who is responsible for keeping it correct.
> **Pairs with:** [MEMORY_SPEC.md](MEMORY_SPEC.md) (company-context vs agent-journal scopes),
> [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) (`read`/`recall`/`remember`/`draft`/`request_approval`/`execute`),
> [CONNECTORS_SPEC.md](CONNECTORS_SPEC.md) (Google Drive as company storage),
> [HIRE_UX.md](HIRE_UX.md) §5 (HR hiring coach), [SECURITY_SPEC.md](SECURITY_SPEC.md) (trust labels).

## Summary

Before an agent does anything productive, it must know the company: mission, products, customers,
brand voice, **team structure and hierarchy**, the tools in use, who's who, and the **norms — the
do's and don'ts and what's expected of an agent**. That knowledge is the company's onboarding
material — a **single shared, canonical body of documents, not a per-agent fact**.

It lives where a real company keeps its documents: **the company's own storage** (Google Drive, or
whatever the company uses), mirrored under `docs/` so it stays accessible even when a connector is
down. Agents read and contribute to it like any other employee would.

Design in one line: **two pre-seeded agents — Enablement produces and stewards the company-wide
material; HR runs hiring — and every shared document is owner-approved before it becomes canon.**

## Two roles — Enablement and HR

The platform pre-seeds **two distinct agents** at install (see *What ships today*). They were one
agent in an earlier draft; they are split because the jobs have different lifecycles.

| Agent | Owns | Lifecycle | Why separate |
|---|---|---|---|
| **`@enablement`** ("Agent Enablement") | The **company-wide onboarding material** — mission, products, customers, brand voice, hierarchy, tools, norms. The onboarding **plan** (the reading list a new hire works through). | Continuous — grows and stays current as the company and team change | Every agent depends on company context, even a lone agent that never hires. Enablement is the **more fundamental** of the two. |
| **`@hr`** ("HR & Hiring") | **Hiring** — coaching the owner through the hire wizard, tightening role briefs, the `pidgin-suggestion` panel ([HIRE_UX.md](HIRE_UX.md) §5). | Episodic — active when the owner grows the team through Pidgin | Recruiting is a different job from stewarding what new hires read. |

Enablement is **not** the author of *all* shared knowledge — it stewards the **company-wide**
material. Team-specific knowledge is authored bottom-up by the team that needs it (see below).

## Where shared knowledge lives — three layers

There is **no special Pidgin "team memory" primitive**. Shared knowledge is just **company
documents in storage**, organized into folders exactly as a real company would, with folder
permissions doing the scoping. Per-agent memory ([MEMORY_SPEC.md](MEMORY_SPEC.md)) is unchanged.

| Layer | Where | Who reads | Who drafts | Write gate |
|---|---|---|---|---|
| **Company context** | Drive / company-wide folder (mirrored to `docs/`) | every agent | **Enablement** (steward, top-down) | **owner-approved** |
| **Team knowledge / SOPs** | Drive / team folder | that team/role | **any agent on that team**, when a gap exists (bottom-up) | **owner-approved** |
| **Per-agent journal** | `memory/<handle>/journal.md` | just that agent | the agent itself (`remember`) | none (private cache) |

Example: a Support agent that needs a refund policy and finds none **drafts** one into the Support
team folder; the owner approves; every future Support agent then onboards from it. The team folder
is both a working reference *and* the onboarding reading for the next hire on that team. Top-down
(Enablement) and bottom-up (teams) meet in the same Drive, under one approval rule.

Per-agent journals stay strictly isolated, so they are the wrong home for shared truth — N agents
would each learn a divergent version. A journal only **caches** the parts of the shared docs
relevant to one agent's role for fast recall; the Drive docs stay authoritative.

## One write rule — owner-approved

Anything that lands in shared company storage — whether Enablement editing the company-wide doc or a
Support agent adding a refund policy — goes through the same gate: `draft` → `request_approval` →
**owner approves** → `execute` writes it, with an audit entry. Private-journal writes are ungated.

This is the guard against contradictions and poisoning: an agent influenced by untrusted content
could otherwise write a bad fact that every other agent then trusts. The blast radius differs (a
team doc misleads one team; the company doc misleads everyone), but the rule is uniform, so there is
one thing to reason about. Agents **never** self-commit to shared storage.

## Lifecycle

### 1. Bootstrap (first time the company sets up)
**Enablement interviews the owner** — mission, products, customers, brand voice, team structure and
hierarchy, tools, key people, and norms (do's and don'ts) — and `draft`s the initial company-wide
material. Nothing becomes canon until the owner approves it. The material is never auto-published.

### 2. Handoff at hire (HR → new agent)
When a hire completes, **HR hands the new agent off by pointing it at the material Enablement
maintains** — "before any productive work, read the onboarding material here → \<pointer into
Drive\>." There is no HR→Enablement coordination per hire: Enablement's output already exists; HR
just points to it. The reading list *is* the onboarding plan.

### 3. Read-once-then-cache (every agent, on first run)
The **first thing** a newly hired agent does is read the company-wide material (and its team folder,
if any), then distill the parts relevant to its role into its journal via `remember`. Subsequent
turns recall from the journal (cheap), not the whole doc set. Each agent records the **version it
onboarded against** (a content hash or version tag) in its journal.

### 4. Refresh-on-change
When shared material changes, its version/hash changes. On turn start the runtime compares the
agent's onboarded version to the current canon; if stale, the agent re-reads and updates its journal
cache. The canon, not the cache, wins whenever they disagree.

### 5. Gap-fill (any agent, any time)
If an agent needs a fact that is missing, it does **not** invent it. For **company-wide** facts it
asks the owner or proposes the fact, routed to **Enablement**, who consolidates it for owner
approval. For **team** facts the agent drafts directly into its team folder for owner approval. Both
end at the same gate; approved facts trigger a refresh for everyone in scope.

## Responsibilities

| Actor | Reads canon | Drafts / proposes | Commits to shared storage |
|---|---|---|---|
| Every agent | **yes (mandatory, first)** | yes — gap-fill to Enablement (company) or own team folder | no — owner-gated |
| **Enablement** (steward) | yes | **yes — owns the company-wide material**; consolidates gap-fills | **prepares**, then owner-approved |
| **HR** (hiring) | n/a for stewardship | proposes role briefs in the hire wizard | n/a — does not steward canon |
| Workspace owner (human) | n/a | n/a | **approves every change** |

This is deliberately **not** "each agent owns its own onboarding" (isolation defeats sharing) and
**not** "any agent writes company truth freely" (contradictions + poisoning). Writes to shared
storage are always human-approved.

## Trust & safety

- The onboarding material is **trusted instruction context** once approved, so the approval gate is
  what protects it. Gap-fill proposals derived from untrusted content (emails, scraped pages) must
  carry their trust label so Enablement/owner reviews them as untrusted before they become canon
  ([SECURITY_SPEC.md](SECURITY_SPEC.md)).
- Agents must never publish or commit to shared storage without owner approval — `execute` is gated.

## What ships today vs. needs runtime work

**Ships today (no runtime change):**
- **Two pre-seeded agents.** The starting team is **data, not code**: workspace creation reads a
  seed manifest ([workspace-seed.json](../recipes/workspace-seed.json)) and hires each listed recipe
  — **`@enablement`** ([enablement-v0.1.json](../recipes/enablement-v0.1.json)) and **`@hr`**
  ([hr-onboarding-v0.1.json](../recipes/hr-onboarding-v0.1.json)). Seeding is idempotent (singleton
  roles / taken handles are skipped).
- **Reconciliation backfill.** Because the manifest is the desired state and seeding is idempotent, a
  reconciliation pass runs over every registered workspace at API startup (and is callable on
  demand), so workspaces created before an agent was added to the manifest — e.g. Enablement — gain
  it without manual migration.
- **Recipe-prompt instruction** in every role telling agents to read company context first and to
  propose (not invent) missing facts. Company-context recall already exists in MEMORY_SPEC.

**Needs runtime work (specced here, not yet built):**
1. **First-read bootstrap** — runtime ensures a new agent's first action reads the onboarding
   material (or injects it) before productive work, rather than relying on the prompt alone.
2. **Versioned canon + refresh signal** — a content hash/version on the material, an
   `onboarded_version` marker per agent, and a turn-start staleness check that triggers re-read.
3. **Shared-storage write path with approval** — committing approved content to `docs/` + Drive as a
   gated `execute`, with an audit entry, for both company-wide and team folders.
4. **Gap-fill routing** — a company-wide proposal reaches Enablement's queue; a team proposal lands
   in the team folder's approval queue.

## Open decisions

| # | Decision | Status |
|---|---|---|
| 1 | Canon format — single Markdown doc vs. sectioned docs (mission / brand / **hierarchy** / **norms** / people / tools) | TBD; lean sectioned for targeted recall |
| 2 | Hierarchy representation — freeform prose vs. a structured roster the runtime can also use for routing/delegation | TBD; structured roster lets Enablement keep the org map current as a byproduct of every hire |
| 3 | Refresh granularity — whole-doc hash vs. per-section | TBD |
| 4 | Where Drive sits vs. the `docs/` mirror — Drive as source with local cache, or local as source synced to Drive | TBD |
| 5 | Whether first-read is a hard runtime gate or an auto-injection | Leaning auto-inject + prompt; gate is heavier |
| 6 | Team-folder curation — does a team lead agent curate its folder, or only the owner approves | TBD; owner-approval holds today |
