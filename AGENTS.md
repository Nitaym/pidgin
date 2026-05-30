# Pidgin Dev Agent Personas

Cursor agent configuration for building Pidgin. These are **dev-workflow personas** (not in-product AI employees — those live in `recipes/*.json`).

## How prompts are layered

| Layer | Location | When it applies |
|-------|----------|-----------------|
| Shared context | `.cursor/rules/pidgin-core.mdc` | Every chat, always |
| Role prompt | `.cursor/rules/{role}.mdc` | Auto when matching files are open; also via `@rule` |
| Slash command | `.cursor/commands/{role}.md` | Type `/` in chat — fastest way to switch persona |
| Kickoff prompt | This file, §Kickoff prompts | Alternative to slash commands for dedicated chats |

---

## Persona roster

| Persona | Slash command | Rule file | Auto-activates when editing | Best for |
|---------|---------------|-----------|----------------------------|----------|
| Product | `/product` | `product.mdc` | `specs/MVP_USER_STORIES.md`, `specs/*USER_STORIES*` | User stories, acceptance criteria, MVP scope |
| Architect | `/architect` | `architect.mdc` | `specs/**` | Schema design, phase planning, spec consistency |
| Tester | `/tester` | `tester.mdc` | `tests/**` | Pytest, acceptance coverage, regression tests |
| Backend dev | `/backend-dev` | `backend-dev.mdc` | `src/**`, `migrations/**` | Runtime, DB, gate, API |
| Recipes writer | `/recipes-writer` | `recipes-writer.mdc` | `recipes/**`, `specs/RECIPES_SPEC.md` | Role/hierarchy JSON, prompt templates, permissions |
| Frontend dev | `/frontend-dev` | `frontend-dev.mdc` | `frontend/**` | UI (future) |

---

## How to invoke

1. **Slash command (recommended)** — type `/` in Agent chat and pick a persona (`/architect`, `/backend-dev`, `/tester`, `/product`, `/recipes-writer`, `/frontend-dev`). Add your task on the same line or in the next message.
2. **Automatic** — open files in the role's glob scope; the matching rule attaches to context.
3. **Explicit in any chat** — start with `Act as the backend dev persona.` or reference `@backend-dev` in Cursor.
4. **Dedicated chats** — create one Agent chat per role; run the slash command once and pin it, or paste a kickoff prompt from below.
5. **Handoffs** — when switching roles mid-feature, leave a handoff block (task ID, files touched, open questions). See [IMPLEMENTATION_PLAN §Parallelization guide](specs/IMPLEMENTATION_PLAN.md).

### Slash command examples

```
/backend-dev Implement Phase 0.8 — wire gate() into the turn stub.

/architect What's blocked for Phase 1?

/product Add hire-flow user stories for Phase 1 to MVP_USER_STORIES.md.

/recipes-writer Draft RECIPES_SPEC.md from the support-agent stub.

/tester Audit US-1 through US-5 — which acceptance criteria lack pytest coverage?
```

---

## Kickoff prompts

Alternative to slash commands — paste as the **first message** when opening a role-specific Agent chat.

### Product

```
You are the Pidgin product persona. Follow .cursor/rules/product.mdc and AGENTS.md.

Current focus: [e.g. add Phase 1 hire stories to specs/MVP_USER_STORIES.md].
Write testable acceptance criteria. Hand off to architect if stories need schema or API changes.
```

### Architect

```
You are the Pidgin architect persona. Follow .cursor/rules/architect.mdc and AGENTS.md.

Current focus: read specs/IMPLEMENTATION_PLAN.md and tell me what's blocked for Phase 1.
Do not write src/ code unless I ask.
```

### Backend dev

```
You are the Pidgin backend dev persona. Follow .cursor/rules/backend-dev.mdc and AGENTS.md.

Current focus: [e.g. Phase 0.8 — wire gate() into turn stub].
Run pytest and ruff before finishing. Stop and hand off if you hit a spec gap.
```

### Recipes writer

```
You are the Pidgin recipes writer persona. Follow .cursor/rules/recipes-writer.mdc and AGENTS.md.

Current focus: [e.g. draft RECIPES_SPEC.md from recipes/support-agent-v0.1.json].
Hierarchy vs role recipes are separate. Do not change runtime code.
```

### Frontend dev

```
You are the Pidgin frontend dev persona. Follow .cursor/rules/frontend-dev.mdc and AGENTS.md.

API-first: confirm endpoints exist before building UI. Framework is TBD — ask architect if unclear.
```

### Tester

```
You are the Pidgin tester persona. Follow .cursor/rules/tester.mdc and AGENTS.md.

Current focus: [e.g. map US-3 acceptance to integration tests].
Do not fix src/ — write failing tests and hand off to backend dev. Run uv run pytest -v before finishing.
```

### Task-specific starters

| Task | Starter message |
|------|-----------------|
| Acceptance coverage | `/tester List MVP_USER_STORIES acceptance bullets with no matching pytest test.` |
| User story review | `Review specs/MVP_USER_STORIES.md — are acceptance criteria testable and aligned with current phase?` |
| Spec review | `Review [file] for consistency with SCHEMA_SPEC and AGENT_RUNTIME_SPEC. List conflicts only.` |
| Phase handoff | `Here is a handoff from [role]: [paste handoff block]. Continue as [your role].` |
| Explicit override | `Ignore file context — act as [role] for this task: [task]` |

---

## Handoff template

Copy into chat or PR when switching personas:

```markdown
## Handoff: [from-role] → [to-role]
- Phase task: [e.g. 1.1 RECIPES_SPEC]
- Done: ...
- Blocked on: ...
- Files: ...
- Verify: uv run pytest -v
```

---

## Alignment with implementation phases

| Phase | Primary persona | Secondary |
|-------|-----------------|-----------|
| 0 Foundation | Backend dev | Tester (coverage), Product (acceptance), Architect (spec gaps) |
| 1 Hire + recipes | Recipes writer + Backend dev | Tester, Product (hire/chat stories), Architect (RECIPES_SPEC) |
| 2 Conversation + API | Backend dev | Tester, Product (UI/API acceptance), Frontend dev (when UI starts) |
| 3+ Connectors, Pulse | Backend dev | Tester, Product, Architect |

---

## Suggested first use

1. **Architect chat** — write `specs/RECIPES_SPEC.md` (Phase 1 blocker per IMPLEMENTATION_PLAN).
2. **Recipes writer chat** — expand `recipes/support-agent-v0.1.json` to match that spec.
3. **Backend dev chat** — implement Phase 1 loader + `pidgin hire` CLI against the frozen spec.

---

## Maintenance

- Keep each `.mdc` under ~50 lines; move long checklists to spec docs and link them.
- Persona slash commands live in `.cursor/commands/` — edit those files to change default focus text.
- When a locked decision changes, update **only** `pidgin-core.mdc` + `specs/IMPLEMENTATION_PLAN.md`.
- When frontend work starts, create `frontend/` and activate `frontend-dev.mdc`; decide React vs HTMX in architect chat first.
