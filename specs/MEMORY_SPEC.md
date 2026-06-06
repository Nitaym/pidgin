# Memory management

> **Scope:** How Pidgin stores, recalls, and maintains agent memory. Pairs with [AGENT_RUNTIME_SPEC.md §5](AGENT_RUNTIME_SPEC.md) (scopes and recall) and [SCHEMA_SPEC.md §4](SCHEMA_SPEC.md) (file layout).

## Summary

Agent memory is **append-only text** — one `journal.md` per hired agent under `memory/<handle>/`. Agents write via `remember`; the runtime injects context via `recall` (tail + grep). There is **no vector DB** and no automatic deduplication in MVP.

Because journals only grow, **memory cleaning is required**. Without it, recall quality degrades, disk use grows, and grep hits stale or contradictory facts.

## What lives where

| Scope | Path | Writer | Recall (MVP) |
|---|---|---|---|
| Agent memory | `memory/<handle>/journal.md` | Agent (`remember`) | Tail (~8 KB) + keyword grep |
| Company context | `docs/<id>.txt` + DB catalog | Runtime / admin | Grep or whole file if small (~32 KB) |
| Conversation state | DB (`conversations`, `messages`) | Runtime + agent | Per-turn from DB, not the journal |

Per-agent isolation is strict: Jane's journal is invisible to Max. Cross-agent context flows only through granted documents or explicit `delegate`.

## Why cleaning is required

1. **Recall is bounded** — only the journal tail and grep matches enter a turn. Old entries fall out of the default context even though they remain on disk.
2. **Journals are append-only** — every `remember` adds material; nothing is removed unless something explicitly cleans.
3. **Stale facts accumulate** — decisions change, contacts leave, policies update. Uncleaned journals mix current and obsolete notes.
4. **Operational cost** — large files slow grep and make human inspection harder.

Cleaning is a **first-class lifecycle concern**, not an optional optimization.

## What cleaning means (outcomes, not mechanism)

Cleaning should produce one or more of:

- **Smaller active journal** — fewer bytes/lines in the file used for recall.
- **Consolidated facts** — many dated blocks replaced by fewer up-to-date summaries.
- **Archived history** — superseded content moved out of the hot path but retained for audit if needed.
- **Explicit tombstones** — removed or invalidated entries recorded so agents do not re-remember the same stale fact.

The MVP does **not** define how cleaning runs. Implementation is deferred; options below are proposals only.

## Cleaning options (proposals — not decided)

| Option | Trigger | Pros | Cons |
|---|---|---|---|
| **Agent self-maintenance** | Recipe behavior or periodic `schedule_self` turn | Context-aware; agent knows what is obsolete | Unreliable if not prompted; uses LLM budget |
| **Summarize-and-replace** | Job or admin action runs LLM over old blocks → writes consolidated `remember` entries → archives or deletes source blocks | Keeps journal human-readable; improves recall signal | Needs gate/audit for destructive edits; summary quality risk |
| **Retention by age** | Background job drops or archives entries older than N days | Simple, predictable | May delete still-relevant long-tail facts |
| **Operator manual trim** | Admin UI or CLI on `journal.md` | Full human control | Does not scale; easy to break format |
| **Offboarding archive** | On agent fire/pause: move `journal.md` → `journal.archive.md`, start empty journal on re-hire | Clean separation per employment period | Re-hired agent loses hot memory unless restored |
| **Tiered storage** | Hot `journal.md` + cold `journal.archive.md`; recall searches both with lower priority on archive | Preserves history without bloating tail | Two-file recall logic; archive search cost |

**Recommendation for planning:** treat **summarize-and-replace** plus **offboarding archive** as the likely long-term shape; start MVP with **operator visibility** (journal size, last cleaned) and document that automatic cleaning is post-MVP.

## Open decisions

| # | Decision | Status |
|---|---|---|
| 1 | Who may trigger cleaning (agent, operator, runtime job only) | TBD |
| 2 | Whether cleaned content is deleted, archived, or superseded in-place | TBD |
| 3 | Default retention / compaction schedule | TBD |
| 4 | Audit requirement for cleaning actions (`agent_action_log` entries) | TBD — likely required |

Record resolved choices in [IMPLEMENTATION_PLAN.md §Open decisions](IMPLEMENTATION_PLAN.md).

## Related specs

- [AGENT_RUNTIME_SPEC.md §5](AGENT_RUNTIME_SPEC.md) — `remember` / `recall` behavior
- [SCHEMA_SPEC.md §4](SCHEMA_SPEC.md) — workspace file layout
- [SECURITY_SPEC.md](SECURITY_SPEC.md) — trust labels on recalled content
- [PRODUCT_SPEC.md](PRODUCT_SPEC.md) — memory in the AI employee model

## Handoff

- **Fullstack dev** — when implementing cleaning: add tests for journal integrity, gate any destructive path, log to `agent_action_log`.
- **Product** — if operator-facing controls are needed, add US-* acceptance criteria for journal health and manual archive.
- **Recipes writer** — optional recipe fields for maintenance cadence or self-cleaning instructions once option (1) or (2) is chosen.
