# Marketing Team — Design Sketch

**Status:** Exploratory. Not MVP. The three specialist recipes below ship today; the *team* layer
depends on multi-agent delegation that the runtime supports as an action (`delegate`) but does not
yet orchestrate as a hierarchy. See [RECIPES_SPEC.md](RECIPES_SPEC.md) §7 ("Hierarchy recipes are
out of scope for MVP").

**Related:** [RECIPES_SPEC.md](RECIPES_SPEC.md), [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md)
(`delegate`, `escalate`, requester chain), [SECURITY_SPEC.md](SECURITY_SPEC.md).

---

## 1. What ships today (three independent specialists)

| Recipe | `recipe_id` | Drafts | Publishes |
|---|---|---|---|
| Content Marketing Writer | `marketing-content-writer` | emails, newsletters, blog, landing pages | never — owner approves |
| Campaign Manager | `marketing-campaign-manager` | plans, briefs, calendars, status | never — owner approves |
| Social Media Manager | `marketing-social-manager` | social posts, reply drafts | never — owner approves |

All three are **draft-only**: `execute` is in `requires_approval`, and `delegate` is `blocked`. A
human is always the publisher. Each can be hired independently and used standalone today.

## 2. The team layer (sketch)

The idea: instead of the owner coordinating three specialists by hand, hire a **Marketing Lead** that
receives the goal, decomposes it, and delegates to the specialists — with the owner still approving
every outbound action.

```
                 owner (commander)
                      │  goal: "launch campaign for Feature X"
                      ▼
            ┌──────────────────────┐
            │   Marketing Lead     │  plans, decomposes, delegates, consolidates
            │  (can_write: delegate)│  → stages everything for owner approval
            └──────────┬───────────┘
          delegate     │     delegate            delegate
        ┌──────────────┼────────────────────┬───────────────┐
        ▼              ▼                     ▼
  Content Writer   Campaign Manager     Social Manager
   (drafts copy)   (plan + calendar)    (social drafts)
        │              │                     │
        └──────────────┴─────────────────────┘
                       │ drafts bubble up
                       ▼
              owner approves → publish
```

### 2.1 Proposed Marketing Lead recipe (not yet bundled)

Same draft-only safety posture, but **`delegate` moves from `blocked` to `can_write`**:

```json
{
  "recipe_id": "marketing-lead",
  "role_title": "Head of Marketing",
  "permissions": {
    "can_read": ["read", "recall", "watch"],
    "can_write": ["say", "post", "remember", "draft", "open_task",
                  "schedule_self", "request_approval", "delegate", "escalate", "close"],
    "requires_approval": ["execute"],
    "blocked": []
  }
}
```

The lead's prompt would: turn a goal into a plan, delegate discrete pieces to the right specialist,
preserve the original requester chain on each handoff, consolidate the returned drafts, and present
the owner a single approve/reject surface instead of three.

## 3. What the runtime needs before the team is real

The `delegate` action type exists, but for a hierarchy to work end to end we need:

1. **Addressing** — how the Lead names a target specialist (handle? role? a registered roster on the
   Lead's employee row). MVP recipes have no roster field.
2. **Requester-chain propagation** — the executive-assistant prompt already references "preserve the
   original requester chain"; the team needs this enforced so a delegated draft is still attributed to
   the owner's original request for approval/audit.
3. **Trust on peer handoffs** — a `PEER_DELEGATION` trigger already exists
   ([enums.py](../src/pidgin/types/enums.py) `TriggerType.PEER_DELEGATION`); the gate must decide how a
   peer-delegated instruction is trusted vs. an owner instruction.
4. **Consolidated approval UX** — one owner approval over a bundle of specialist drafts, not N
   separate prompts.

## 4. Recommended path

1. **Now:** ship the three specialists; let the owner coordinate them manually. Validates the prompts
   and the draft-only posture with zero new runtime work.
2. **Next:** add a roster concept to the recipe/employee schema and a `marketing-lead` recipe; wire
   `delegate` addressing + requester-chain propagation.
3. **Later:** consolidated multi-draft approval UX, and per-specialist connectors (social platforms,
   analytics) so "publish" and "report" become real instead of hand-back-to-owner.
