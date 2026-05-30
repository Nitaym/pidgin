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
| [main_features.md](main_features.md) | Short feature notes |

## MVP technical decisions (locked)

- **Language:** Python 3.12+
- **Storage:** one workspace directory = plain SQLite + text files (`memory/`, `docs/`, `blobs/`)
- **Memory:** per-agent `journal.md` append-only; recall = tail + grep (no vector DB)
- **Password:** one per workspace; caller supplies at open; bcrypt hash in `auth.json` only — Pidgin does not store passwords or integrate with OS keychain
- **Secrets (production):** inject from env / K8s Secret / Vault — not MVP scope
- **Not in MVP:** sqlite-vec, SQLCipher, Argon2/AES credential encryption, OS keychain

## Reading order

1. [PRODUCT_SPEC.md](PRODUCT_SPEC.md) — why we're building this
2. [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) §2–3 — trigger and action vocabulary
3. [SCHEMA_SPEC.md](SCHEMA_SPEC.md) §2 — all tables at a glance
4. [TECH_STACK_SPEC.md](TECH_STACK_SPEC.md) §2 — stack at a glance
5. Drill into detail sections as needed
