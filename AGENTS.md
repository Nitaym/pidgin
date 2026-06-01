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
| Fullstack dev | `/fullstack` | `fullstack.mdc` | `src/**`, `tests/**`, `migrations/**` | Backend, frontend; pytest + **manual UI** in browser |
| Recipes writer | `/recipes-writer` | `recipes-writer.mdc` | `recipes/**`, `specs/RECIPES_SPEC.md` | Role/hierarchy JSON, prompt templates, permissions |

---

## How to invoke

1. **Slash command (recommended)** — type `/` in Agent chat and pick a persona (`/fullstack`, `/architect`, `/product`, `/recipes-writer`). Add your task on the same line or in the next message.
2. **Automatic** — open files in the role's glob scope; the matching rule attaches to context.
3. **Explicit in any chat** — start with `Act as the fullstack dev persona.` or reference `@fullstack` in Cursor.
4. **Dedicated chats** — create one Agent chat per role; run the slash command once and pin it, or paste a kickoff prompt from below.
5. **Handoffs** — when switching roles mid-feature, create a **Linear ticket** with the handoff block below. State clearly **who you are handing off to** (target persona). See [IMPLEMENTATION_PLAN §Parallelization guide](specs/IMPLEMENTATION_PLAN.md).

### Slash command examples

```
/fullstack Implement the hire wizard step 3 change and manually verify US-6 in the browser.

/architect What's blocked for Phase 1?

/product Add hire-flow user stories for Phase 1 to MVP_USER_STORIES.md.

/recipes-writer Draft RECIPES_SPEC.md from the support-agent stub.
```

---

## Manual UI testing (fullstack dev)

**Policy:** UI acceptance is verified **manually in a real browser** via Cursor's browser tools — not Playwright or `tests/e2e/` specs (deferred until explicitly requested).

### Start the app

```bash
# Terminal A — API (dev auth for local testing)
PIDGIN_ALLOW_DEV_AUTH=1 uv run pidgin-admin --home ~/.pidgin

# Terminal B — frontend
cd src/frontend && npm run dev
# → http://127.0.0.1:5173
```

Use **Dev sign-in (local only)** on `/login`, then exercise the flow from `specs/MVP_USER_STORIES.md`.

### Agent checklist (before marking UI work done)

1. Read the US-* story acceptance bullets.
2. Navigate the UI step by step in the browser tool.
3. Capture snapshot/screenshot at key steps.
4. Report:

```markdown
## Manual UI verification — US-[N]
- [ ] criterion 1 — pass/fail + note
- [ ] criterion 2 — pass/fail + note
```

5. If a criterion fails, fix or hand off to product/architect — do not skip verification.

**Backend-only changes:** `uv run pytest -v` is sufficient; no browser pass required.

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

### Fullstack dev

```
You are the Pidgin fullstack dev persona. Follow .cursor/rules/fullstack.mdc and AGENTS.md.

Current focus: [e.g. hire wizard step 3].
Backend: pytest. UI: manually verify US-* in browser (no Playwright). Run ruff + pytest before finishing.
```

### Recipes writer

```
You are the Pidgin recipes writer persona. Follow .cursor/rules/recipes-writer.mdc and AGENTS.md.

Current focus: [e.g. draft RECIPES_SPEC.md from recipes/support-agent-v0.1.json].
Hierarchy vs role recipes are separate. Do not change runtime code.
```

### Task-specific starters

| Task | Starter message |
|------|-----------------|
| Manual UI check | `/fullstack Manually verify US-[N] in the browser against MVP_USER_STORIES.md.` |
| User story review | `Review specs/MVP_USER_STORIES.md — are acceptance criteria testable and aligned with current phase?` |
| Spec review | `Review [file] for consistency with SCHEMA_SPEC and AGENT_RUNTIME_SPEC. List conflicts only.` |
| Phase handoff | Open the Linear handoff ticket, then: `Continue as [your role] — see Linear ticket [ID].` |
| Explicit override | `Ignore file context — act as [role] for this task: [task]` |

---

## Handoff template

**Handoffs go in Linear.** Create or update a ticket when switching personas; do not rely on chat-only handoffs.

- **Title:** include both roles, e.g. `Handoff: product → fullstack`
- **Assignee / label:** set the **handoff target** — the persona (or person) who should pick up the work
- **Description:** use this block:

```markdown
## Handoff: [from-role] → [to-role]

**Hand off to:** [to-role] (required — name the persona taking over)

- Phase task: [e.g. 1.1 RECIPES_SPEC]
- Done: ...
- Blocked on: ...
- Files: ...
- Verify: `uv run pytest -v` (backend); manual UI checklist for US-* (frontend)
```

The receiving agent should start from the Linear ticket (link or ID in chat is fine).

---

## Alignment with implementation phases

| Phase | Primary persona | Secondary |
|-------|-----------------|-----------|
| 0 Foundation | Fullstack dev | Product (acceptance), Architect (spec gaps) |
| 1 Hire + recipes | Recipes writer + Fullstack dev | Product (hire/chat stories), Architect (RECIPES_SPEC) |
| 2 Conversation + API | Fullstack dev | Product (UI/API acceptance) |
| 3+ Connectors, Pulse | Fullstack dev | Product, Architect |

---

## Suggested first use

1. **Architect chat** — write `specs/RECIPES_SPEC.md` (Phase 1 blocker per IMPLEMENTATION_PLAN).
2. **Recipes writer chat** — expand `recipes/support-agent-v0.1.json` to match that spec.
3. **Fullstack chat** — implement a feature; pytest for API, manual browser pass for UI stories.

---

## Maintenance

- Keep each `.mdc` under ~50 lines; move long checklists to spec docs and link them.
- Persona slash commands live in `.cursor/commands/` — edit those files to change default focus text.
- Fullstack dev verifies UI stories manually in browser; Playwright e2e in `tests/e2e/` is **not** required at this stage.
- When a locked decision changes, update **only** `pidgin-core.mdc` + `specs/IMPLEMENTATION_PLAN.md`.
