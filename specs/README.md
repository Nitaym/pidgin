# Pidgin Specs

Documentation for the Pidgin AI workforce platform. Read top-down: product vision → runtime behavior → storage → stack.

## Spec index

| Spec | What it covers |
|---|---|
| [PRODUCT_SPEC.md](PRODUCT_SPEC.md) | Product vision, recipes, entities, MVP scope, user flows |
| [SECURITY_SPEC.md](SECURITY_SPEC.md) | Trust labels, invocation policy, instructions vs data, audit |
| [INTEGRATION_WOFKLOW.md](INTEGRATION_WOFKLOW.md) | Connectors, virtual agent identities, attribution |
| [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) | 8 triggers, 14 actions, turns, gate, process model |
| [SCHEMA_SPEC.md](SCHEMA_SPEC.md) | 26 DB tables, file-based memory, workspace layout |
| [TECH_STACK_SPEC.md](TECH_STACK_SPEC.md) | Python MVP stack, libraries, deliberate omissions |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Phased build plan, current status, agent handoff |
| [MVP_USER_STORIES.md](MVP_USER_STORIES.md) | Acceptance criteria for Phase 0–2 |
| [HIRE_UX.md](HIRE_UX.md) | Hire wizard UX, templates, HR assist vocabulary |
| [RECIPES_SPEC.md](RECIPES_SPEC.md) | Role recipe JSON schema, hire pre-fill fields |
| [main_features.md](main_features.md) | Short feature notes |

## MVP technical decisions (locked)

- **Language:** Python 3.12+
- **Storage:** one workspace directory = plain SQLite + text files (`memory/`, `docs/`, `blobs/`)
- **Memory:** per-agent `journal.md` append-only; recall = tail + grep (no vector DB)
- **Operator auth:** Google OAuth session cookie (dev: `POST /api/auth/dev-login` when `PIDGIN_ALLOW_DEV_AUTH=1`)
- **Workspace:** one workspace per install; internal bcrypt in `auth.json` is not exposed to users
- **Secrets (production):** inject from env / K8s Secret / Vault — not MVP scope
- **Not in MVP:** sqlite-vec, SQLCipher, Argon2/AES credential encryption, OS keychain

## Dev setup

**Backend + API**

```bash
uv sync --all-extras
uv run pidgin-admin --home ~/.pidgin
# API → http://127.0.0.1:8765/docs
# Set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET (see .env.example) or PIDGIN_ALLOW_DEV_AUTH=1 for local dev
```

**Frontend (Vite + React)** — run in a second terminal:

```bash
cd src/frontend
npm install
npm run dev
# UI → http://127.0.0.1:5173  (proxies /api to pidgin-admin)
```

**Production-style** (single server serves built UI + API):

```bash
cd src/frontend && npm install && npm run build
uv run pidgin-admin --home ~/.pidgin
# → http://127.0.0.1:8765/
```

**Dropbox / synced folders:** if `uv sync` warns about missing `RECORD` files, close Python processes and run `.\scripts\repair-venv.ps1`. `pyproject.toml` sets `[tool.uv] link-mode = "copy"`.

## Reading order

1. [PRODUCT_SPEC.md](PRODUCT_SPEC.md) — why we're building this
2. [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) §2–3 — trigger and action vocabulary
3. [SCHEMA_SPEC.md](SCHEMA_SPEC.md) §2 — all tables at a glance
4. [TECH_STACK_SPEC.md](TECH_STACK_SPEC.md) §2 — stack at a glance
5. Drill into detail sections as needed
