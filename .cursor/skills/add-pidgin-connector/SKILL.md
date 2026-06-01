---
name: add-pidgin-connector
description: >-
  Adds a new Pidgin workspace integration (connector) end-to-end — backend module,
  ingress, OAuth and manual auth, admin API, React Integrations UI, and tests.
  Use when implementing Slack, Gmail, Google Drive, Google Meet, Zoom, or any
  new connector_type, or when the user mentions integrations, connectors, or
  INTEGRATION_WOFKLOW / CONNECTORS_SPEC work.
---

# Add Pidgin Connector

Read [specs/CONNECTORS_SPEC.md](../../specs/CONNECTORS_SPEC.md) first. Do not invent trigger/action vocabulary or table shapes.

## Before coding

1. Confirm `connector_type` is listed in CONNECTORS_SPEC §3 and note its build order slot.
2. Read existing connectors under `src/pidgin/connectors/` — match patterns.
3. Check phase task ID in [specs/IMPLEMENTATION_PLAN.md](../../specs/IMPLEMENTATION_PLAN.md) Phase 2I.

## Locked rules

- Every external side effect: `gate()` → connector method → `agent_action_log` row.
- Ingress **only** inserts `inbound_events` — never calls LLM directly.
- Resource URIs use CONNECTORS_SPEC §4 — add parser cases in `resources.py`.
- Credentials in `connector_installations.credentials_json` only — not env, not recipe JSON.
- User-facing UI says "integration" / "connection"; code uses `connector_type`.
- Ship **full** connect UI (OAuth + manual if spec allows) before marking task done.

## Implementation checklist

Copy to your working notes and check off:

```
- [ ] 1. Spec — CONNECTORS_SPEC §8/§11 entry complete (auth fields, scopes, ingress routes)
- [ ] 2. Package — src/pidgin/connectors/<type>/ (connector.py, ingress.py, oauth.py if needed)
- [ ] 3. Register — registry.register() on import or explicit bootstrap
- [ ] 4. Resource URIs — parse + resolve in resources.py
- [ ] 5. Egress — read / write(draft|execute) / subscribe per §5.1
- [ ] 6. Ingress — normalize payload §6; principals + trust_label
- [ ] 7. API — routes under /api/workspaces/{id}/integrations + webhooks in /hooks/
- [ ] 8. UI — IntegrationsPage card: OAuth, manual advanced, health, disconnect
- [ ] 9. Action wiring — runtime/actions/ dispatches to registry for this prefix
- [ ] 10. Tests — tests/unit/connectors/ + tests/integration/connectors/
- [ ] 11. Verify — uv run pytest -v && uv run ruff check src tests
- [ ] 12. Manual — connect in browser; health green; one ingress/egress smoke path
```

Detailed per-layer notes: [checklist.md](checklist.md).

## File touch map (typical)

| Area | Files |
| --- | --- |
| Core | `connectors/base.py`, `connectors/resources.py`, `connectors/<type>/` |
| DB/service | `services/integrations.py`, `db/connectors.py` (if needed) |
| API | `api/routes/integrations.py`, `api/routes/hooks.py` |
| Runtime | `runtime/actions/read.py`, `post.py`, `draft.py`, `execute.py` |
| Frontend | `pages/IntegrationsPage.tsx`, `api/client.ts`, nav in `Layout.tsx` |
| Tests | `tests/unit/connectors/test_<type>.py`, `tests/integration/connectors/` |

## Auth implementation

**OAuth2:** `POST .../oauth/start` → provider → `GET .../oauth/callback` → store refreshable credentials §2.1.

**Manual:** `POST .../manual` with typed `fields` from CONNECTORS_SPEC §11 for that type. Show dev-only banner in UI unless spec marks production-supported.

Google family (`gmail`, `google_drive`, `google_meet`): reuse shared OAuth client config; separate installation rows per type.

## Ingress template

```python
async def handle_inbound(raw: ProviderPayload, conn: Connection) -> str:
    principal_id = upsert_principal(conn, ...)
    trust = classify_trust(principal_id, raw)
    agent_id = route_to_agent(conn, raw)
    event_id = insert_inbound_event(conn, InboundEventCreate(
        trigger_type=TriggerType....,
        target_ai_employee_id=agent_id,
        sender_principal_id=principal_id,
        trust_label=trust,
        payload=normalize_payload(raw, installation_id),
    ))
    run_once(conn)
    return event_id
```

## Done when

- CONNECTORS_SPEC §11 checklist for this type is satisfied.
- Integrations UI connect/disconnect works for both auth modes the spec allows.
- pytest green; manual smoke documented in PR or chat.
- IMPLEMENTATION_PLAN Phase 2I task ID cited in commit message.

## Hand off

- **Architect** — new `connector_type` not in §3, schema change, or gate semantics gap.
- **Product** — user-facing copy or US-* acceptance unclear.
