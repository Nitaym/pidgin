# Pidgin Tech Stack Spec

## Summary

```text
MVP runtime: Python 3.12+, single process, offline-capable, one workspace directory per tenant (plain SQLite + text files). FastAPI for HTTP/WebSocket. Official LLM and connector SDKs. No vector DB, no OS keychain, no credential encryption in MVP — deliberate simplification.
```

The short product line:

```text
Python you know. SQLite for structure. Markdown for memory. Ship the loop, not the infrastructure.
```

> **Scope:** Language, libraries, and tooling for the Pidgin runtime MVP. Pairs with [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) and [SCHEMA_SPEC.md](SCHEMA_SPEC.md).
>
> **Out of scope:** Recipe marketplace stack, frontend framework final choice, production deployment (K8s, Nuitka builds) — noted as post-MVP paths.

---

## Table of Contents

1. [Constraints](#1-constraints)
2. [Stack at a Glance](#2-stack-at-a-glance)
3. [Runtime and Process Model](#3-runtime-and-process-model)
4. [Storage and Secrets](#4-storage-and-secrets)
5. [Web and API Layer](#5-web-and-api-layer)
6. [Agent Runtime Internals](#6-agent-runtime-internals)
7. [Connectors](#7-connectors)
8. [Knowledge and Recall](#8-knowledge-and-recall)
9. [Tooling and Quality](#9-tooling-and-quality)
10. [Explicitly Not in MVP](#10-explicitly-not-in-mvp)
11. [Post-MVP Paths](#11-post-mvp-paths)
12. [Open Decisions](#12-open-decisions)

---

## 1. Constraints

From product and architecture decisions:


| Constraint                      | Implication                                                    |
| ------------------------------- | -------------------------------------------------------------- |
| Single machine, can run offline | One process; no Redis, no message broker, no external DB       |
| DB per workspace                | One SQLite file + companion files per workspace directory      |
| Python (author's skills)        | Primary language for runtime, connectors, gate, scheduler      |
| MVP simplicity                  | No keychain, no Argon2/AES stack, no vector search             |
| Closed-source possible later    | Nuitka or similar for production binaries; not MVP blocker     |
| Separable later                 | LLM gateway, connectors, gate as modules with clean interfaces |


---

## 2. Stack at a Glance


| Layer               | Choice                         | Notes                                                                  |
| ------------------- | ------------------------------ | ---------------------------------------------------------------------- |
| **Language**        | Python 3.12+                   | Author expertise; mature AI/connector SDKs                             |
| **Package manager** | `uv`                           | Fast installs, lockfile, venv                                          |
| **Process**         | Single `pidgind` process       | Scheduler + dispatcher + turn executor + HTTP in one binary invocation |
| **HTTP / WS**       | FastAPI + Uvicorn              | Diagnostics + main API; WebSocket for live updates                     |
| **SQLite**          | stdlib `sqlite3` + `aiosqlite` | Plain SQLite for MVP                                                   |
| **Migrations**      | Alembic                        | Forward-only SQL migrations                                            |
| **DB access**       | SQLAlchemy 2.0 Core            | Typed queries; not the ORM                                             |
| **Validation**      | Pydantic v2                    | Events, actions, config, API models                                    |
| **Password verify** | `bcrypt`                       | Hash in `auth.json`; password never stored                             |
| **LLM**             | `anthropic`, `openai`          | Official SDKs                                                          |
| **Logging**         | `structlog`                    | Structured JSON                                                        |
| **Testing**         | `pytest`, `pytest-asyncio`     |                                                                        |
| **Lint / format**   | `ruff`                         | Replaces flake8, black, isort                                          |
| **Types**           | `pyright` strict               |                                                                        |
| **Memory / docs**   | Files on disk                  | `journal.md`, `docs/*.txt`; grep for recall                            |
| **Frontend**        | Deferred                       | React+Vite or HTMX when UI work starts                                 |


Detail for each row is in sections 3–9.

---

## 3. Runtime and Process Model

One Python process (`pidgind`) containing:


| Component              | Responsibility                                                 |
| ---------------------- | -------------------------------------------------------------- |
| **CLI**                | `create-workspace`, `open`, `run`, admin commands              |
| **Workspace manager**  | Open/close workspace dirs; verify password; hold DB connection |
| **Scheduler loop**     | Poll `agent_timers`; emit `inbound_events`                     |
| **Event dispatcher**   | Poll pending `inbound_events`; start/resume turns              |
| **Turn executor**      | Build context → LLM → gate → actions → audit                   |
| **Policy gate**        | Pure function; see AGENT_RUNTIME_SPEC §8                       |
| **LLM gateway module** | `call(messages, tools, budget) → response`                     |
| **Connector registry** | Slack, email, Jira, … behind uniform interface                 |
| **FastAPI app**        | REST + WebSocket + static files (later)                        |


Async throughout (`asyncio`). I/O-bound work (LLM, connectors, DB via `aiosqlite`) uses `async`; CPU-bound rare paths (PDF extract) use `asyncio.to_thread`.

---

## 4. Storage and Secrets

See [SCHEMA_SPEC.md §4](SCHEMA_SPEC.md) for full layout.


| Concern            | MVP approach                                                |
| ------------------ | ----------------------------------------------------------- |
| Structured data    | `db.sqlite` per workspace                                   |
| Agent memory       | `memory/<handle>/journal.md`                                |
| Document text      | `docs/<id>.txt`                                             |
| Blobs              | `blobs/<ab>/<cd>/<sha256>`                                  |
| Workspace password | Caller supplies at open; bcrypt hash in `auth.json` only    |
| Connector tokens   | Plaintext JSON in DB column `credentials_json`              |
| Password storage   | **Not Pidgin's job.** User's password manager, `.env`, etc. |
| Production secrets | Inject via env / K8s Secret / Vault — adapter post-MVP      |


**Not used in MVP:** `keyring`, `argon2-cffi`, `cryptography` for credential blobs, SQLCipher.

---

## 5. Web and API Layer


| Piece             | Library                                           |
| ----------------- | ------------------------------------------------- |
| Framework         | FastAPI                                           |
| ASGI server       | Uvicorn                                           |
| WebSocket         | FastAPI native / Starlette                        |
| Static UI (later) | FastAPI `StaticFiles` or separate Vite dev server |


Diagnostics routes (read-only over workspace DB) per AGENT_RUNTIME_SPEC §10.1.

---

## 6. Agent Runtime Internals


| Module              | Libraries / approach                                              |
| ------------------- | ----------------------------------------------------------------- |
| ULID IDs            | `python-ulid`                                                     |
| Turn / event models | Pydantic v2                                                       |
| Status changes      | Single helper: write `*_status_log` + update cache atomically     |
| LLM gateway         | `anthropic`, `openai` — wrap behind internal interface            |
| Prompt assembly     | Internal module; inject sense-of-time, journal tail, grep results |
| Debug export        | Write `turn.md` + JSONL under `_debug/` when flag enabled         |


Gate and turn executor are plain Python modules — no framework magic.

---

## 7. Connectors

Uniform interface (AGENT_RUNTIME_SPEC §9.4). MVP connectors TBD by product priority; libraries when implemented:


| Integration       | Library                                   |
| ----------------- | ----------------------------------------- |
| Slack             | `slack-sdk`, `slack-bolt`                 |
| Google Workspace  | `google-api-python-client`, `google-auth` |
| Microsoft Graph   | `msgraph-sdk`                             |
| Jira / Confluence | `atlassian-python-api`                    |
| Email             | `aiosmtplib` + IMAP client TBD            |


All connector calls go through the policy gate first.

---

## 8. Knowledge and Recall

**No vector database. No sqlite-vec. No embedding API calls in MVP.**


| Action            | Implementation                                                        |
| ----------------- | --------------------------------------------------------------------- |
| `remember`        | Append block to `memory/<handle>/journal.md`                          |
| `recall` (memory) | Read tail of journal (~8 KB); grep for keywords                       |
| Ingest document   | Extract text → write `docs/<id>.txt`; insert `ingested_documents` row |
| `recall` (docs)   | Grep granted `docs/*.txt`; or read whole file if < ~32 KB             |


Search upgrades later: ripgrep index → SQLite FTS on file corpus → embeddings if needed.

---

## 9. Tooling and Quality


| Tool                        | Purpose                         |
| --------------------------- | ------------------------------- |
| `uv`                        | Dependencies, lockfile, scripts |
| `ruff`                      | Lint + format                   |
| `pyright` (strict)          | Static types                    |
| `pytest` + `pytest-asyncio` | Tests                           |
| `pytest-cov`                | Coverage (optional)             |


Project layout (TBD at scaffold time): `src/pidgin/` with `runtime/`, `gate/`, `llm/`, `connectors/`, `db/`, `api/`.

---

## 10. Explicitly Not in MVP


| Item                                 | Why deferred                                    |
| ------------------------------------ | ----------------------------------------------- |
| OS keychain (`keyring`)              | User manages passwords externally               |
| Argon2id / AES credential encryption | Over-engineering for local MVP                  |
| `sqlite-vec` / embeddings            | File + grep is enough initially                 |
| SQLCipher                            | Plain SQLite + directory isolation              |
| Nuitka / PyInstaller                 | Dev mode first; ship closed-source binary later |
| Separate microservices               | Monolith with module boundaries                 |
| Postgres / Redis                     | Single-machine SQLite                           |
| Frontend framework lock              | Backend first                                   |


---

## 11. Post-MVP Paths


| Need                       | Likely direction                                                  |
| -------------------------- | ----------------------------------------------------------------- |
| Closed-source distribution | Nuitka compile to native binary                                   |
| Production deployment      | Docker; passwords from K8s Secret                                 |
| DB encryption              | SQLCipher; password as DB key                                     |
| Semantic search            | Embeddings + index; maybe sqlite-vec or external                  |
| Scale-out                  | Per-tenant processes; Postgres migration                          |
| Go rewrite of hot path     | Only if profiling proves Python bottleneck (unlikely — LLM-bound) |


---

## 12. Open Decisions


| #   | Decision                     | Notes                                  |
| --- | ---------------------------- | -------------------------------------- |
| 1   | Frontend                     | React+Vite vs HTMX — when UI starts    |
| 2   | Email connector              | IMAP library choice                    |
| 3   | PDF text extraction          | `pypdf` vs `pdfplumber`                |
| 4   | CLI framework                | `typer` vs `click`                     |
| 5   | First connector to implement | **Locked:** `pidgin_chat` → Slack → Gmail → Drive → Meet → Zoom ([CONNECTORS_SPEC.md](CONNECTORS_SPEC.md)) |


---

## Cross-References

- [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) — Triggers, actions, turn lifecycle
- [SCHEMA_SPEC.md](SCHEMA_SPEC.md) — 26 tables + file layout
- [PRODUCT_SPEC.md](PRODUCT_SPEC.md) — MVP scope

