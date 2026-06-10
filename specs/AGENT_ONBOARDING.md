# Agent Onboarding Documentation

> **Scope:** How every hired agent learns about the company before doing productive work, where
> that knowledge lives, and who is responsible for keeping it correct.
> **Pairs with:** [MEMORY_SPEC.md](MEMORY_SPEC.md) (company-context vs agent-journal scopes),
> [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) (`read`/`recall`/`remember`/`draft`/`request_approval`/`execute`),
> [CONNECTORS_SPEC.md](CONNECTORS_SPEC.md) (Google Drive as company storage),
> [SECURITY_SPEC.md](SECURITY_SPEC.md) (trust labels on untrusted content).

## Summary

Before an agent does anything productive, it must know the company: mission, products, customers,
brand voice, the tools in use, and who's who. That knowledge is the **Agent Onboarding
Documentation** — a single shared, canonical artifact, **not** a per-agent fact.

It lives in the **company-context** layer ([MEMORY_SPEC.md](MEMORY_SPEC.md)), hosted on the
company's storage (Google Drive, or whatever the company uses) and mirrored under `docs/` so it is
always accessible to agents even when a connector is down.

Design in one line: **all agents read it and flag gaps; one HR/Onboarding steward curates it; the
human owner approves every change.**

## Two layers — canon vs. cache

| Layer | Where | Authoritative? | Writer |
|---|---|---|---|
| **Canonical onboarding doc** | company-context (`docs/<id>.txt` + DB catalog), backed by Drive | **yes** — single source of truth | HR steward, **owner-approved** |
| **Per-agent cache** | each agent's `memory/<handle>/journal.md` | no — derived copy | the agent itself (`remember`) |

Per-agent memory is strictly isolated ([MEMORY_SPEC.md](MEMORY_SPEC.md)), so it is the wrong home
for shared company truth — N agents would each learn a divergent version. The journal is only a
**cache** of the canon for fast recall; the canon stays the source of truth.

## Lifecycle

### 1. Bootstrap (first time the company sets up)
The HR/Onboarding steward **interviews the owner** — mission, products, customers, brand voice,
tools, key people — and `draft`s the initial onboarding doc. Nothing becomes canon until the owner
approves it (`request_approval` → owner approves → `execute` writes the doc). The doc is never
auto-published.

### 2. Read-once-then-cache (every agent, on first run)
The **first thing** a newly hired agent does is read the canonical onboarding doc, then distill the
parts relevant to its role into its own journal via `remember`. Subsequent turns recall from the
journal (cheap), not the whole doc.

Each agent records the **version it onboarded against** (a content hash or version tag of the canon)
in its journal.

### 3. Refresh-on-change
When the canonical doc changes, its version/hash changes. On turn start the runtime compares the
agent's onboarded version to the current canon; if stale, the agent re-reads the canon and updates
its journal cache. The canon, not the cache, is authoritative whenever they disagree.

### 4. Gap-fill (any agent, any time)
If an agent needs a company fact that is missing, it does **not** invent it and does **not** write
canon directly. It either **asks the owner** or **proposes the fact** (`draft` / `request_approval`)
and the proposal is routed to the HR steward. The steward consolidates it; the owner approves; the
approved fact is committed to the canon, which triggers a refresh for everyone.

## Responsibilities

| Actor | Reads canon | Flags / proposes gaps | Commits to canon |
|---|---|---|---|
| Every agent | **yes (mandatory, first)** | yes (`draft` / `request_approval` / ask owner) | no |
| HR / Onboarding steward | yes | yes | **prepares**, then owner-approved |
| Workspace owner (human) | n/a | n/a | **approves every change** |

This is deliberately **not** "each agent owns its own onboarding" (isolation defeats sharing) and
**not** "any agent writes company truth freely" (contradictions + poisoning: an agent influenced by
untrusted content could write a bad fact every other agent then trusts). Writes to canon are always
human-approved.

## Trust & safety

- The onboarding doc is **trusted instruction context** once approved, so the approval gate is what
  protects it. Gap-fill proposals derived from untrusted content (emails, scraped pages) must carry
  their trust label so the steward/owner reviews them as untrusted before they become canon
  ([SECURITY_SPEC.md](SECURITY_SPEC.md)).
- Agents must never publish or commit canon without owner approval — `execute` is gated.

## What ships today vs. needs runtime work

**Ships today (no runtime change):**
- The **HR/Onboarding steward recipe** (`recipes/hr-onboarding-v0.1.json`) with the interview +
  curate + propose-only-commit behavior baked into its prompt.
- Recipe-prompt instruction in every role telling agents to read company context first and to
  propose (not invent) missing facts. Company-context recall already exists in MEMORY_SPEC.

**Needs runtime work (specced here, not yet built):**
1. **First-read bootstrap** — runtime ensures a new agent's first action reads the onboarding doc
   (or injects it) before productive work, rather than relying on the prompt alone.
2. **Versioned canon + refresh signal** — a content hash/version on the onboarding doc, an
   `onboarded_version` marker per agent, and a turn-start staleness check that triggers re-read.
3. **Company-context write path with approval** — committing approved content to `docs/` + Drive as
   a gated `execute`, with an audit entry.
4. **Gap-fill routing** — a proposal from any agent reaches the HR steward's queue.

## Open decisions

| # | Decision | Status |
|---|---|---|
| 1 | Canon format — single Markdown doc vs. sectioned docs (mission / brand / people / tools) | TBD; lean sectioned for targeted recall |
| 2 | Refresh granularity — whole-doc hash vs. per-section | TBD |
| 3 | Where Drive sits vs. the `docs/` mirror — Drive as source with local cache, or local as source synced to Drive | TBD |
| 4 | Whether first-read is a hard runtime gate or an auto-injection | Leaning auto-inject + prompt; gate is heavier |
