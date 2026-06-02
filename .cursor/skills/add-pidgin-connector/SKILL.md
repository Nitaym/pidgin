---
name: add-pidgin-connector
description: >-
  Adds a new Pidgin workspace integration (connector) end-to-end — backend module,
  ingress, OAuth and manual auth, admin API, per-integration React setup page, and tests.
  Use when implementing Slack, Gmail, Google Drive, Google Meet, Zoom, or any
  new connector_type, or when the user mentions integrations, connectors, or
  INTEGRATION_WOFKLOW / CONNECTORS_SPEC work.
---

# Add Pidgin Connector

Read [specs/CONNECTORS_SPEC.md](../../specs/CONNECTORS_SPEC.md) first. Do not invent trigger/action vocabulary or table shapes.

## Before coding

1. Confirm `connector_type` is listed in CONNECTORS_SPEC §3 and note its build order slot.
2. Read existing connectors under `src/pidgin/connectors/` — match patterns.
3. Read [HireWizardPage.tsx](../../src/frontend/src/pages/HireWizardPage.tsx) and [IntegrationDetailPage.tsx](../../src/frontend/src/pages/IntegrationDetailPage.tsx) for UI patterns.
4. Check phase task ID in [specs/IMPLEMENTATION_PLAN.md](../../specs/IMPLEMENTATION_PLAN.md) Phase 2I.

## Locked rules

- Every external side effect: `gate()` → connector method → `agent_action_log` row.
- Ingress **only** inserts `inbound_events` — never calls LLM directly.
- Resource URIs use CONNECTORS_SPEC §4 — add parser cases in `resources.py`.
- Credentials in `connector_installations.credentials_json` only — not env, not recipe JSON.
- User-facing UI says "integration" / "connection"; code uses `connector_type`.
- **One dedicated setup page per integration** — no collapsible/folding connect panels on the index.
- Match hire-page visual language: `eyebrow`, `brief-section`, `template-grid`, `hire-page-main`, `review-template`.

## UI architecture (required)

| Route | Page | Purpose |
| --- | --- | --- |
| `/{workspace}/integrations` | `IntegrationsPage` | Catalog grid — cards link to detail pages only |
| `/{workspace}/integrations/{connector_type}` | `IntegrationDetailPage` | Full setup: hero, OAuth tab, manual tab, manage |

**Index page:** status + capability chips + “Configure →” — **no inline connect forms**.

**Detail page sections (always visible, not accordions):**
1. Hero — `IntegrationBrand`, description, capability chips
2. Connect — OAuth primary button and/or manual fields; use `.tabs` when both auth modes exist
3. Manage — status, health check, disconnect (when connected)

Add catalog metadata in [integrationMeta.ts](../../src/frontend/src/utils/integrationMeta.ts) (tagline, accent, monogram).

## Implementation checklist

```
- [ ] 1. Spec — CONNECTORS_SPEC §8/§11 entry complete
- [ ] 2. Package — src/pidgin/connectors/<type>/
- [ ] 3. Register — registry bootstrap
- [ ] 4. Resource URIs — resources.py
- [ ] 5. Egress + ingress
- [ ] 6. API — workspace_api.py /integrations/* routes
- [ ] 7. Catalog — connectors/catalog.py entry (auth_modes, manual_fields, capabilities)
- [ ] 8. UI index — card appears on IntegrationsPage automatically from catalog
- [ ] 9. UI detail — integrationMeta.ts entry; verify /integrations/<type> page
- [ ] 10. OAuth callback redirects to /{slug}/integrations/{type}
- [ ] 11. Tests — unit + integration
- [ ] 12. Manual — browser pass on detail page (OAuth or manual + health)
```

Detailed per-layer notes: [checklist.md](checklist.md).

## File touch map (typical)

| Area | Files |
| --- | --- |
| Core | `connectors/<type>/`, `connectors/catalog.py` |
| API | `api/routes/workspace_api.py`, `api/routes/hooks.py` |
| Frontend index | `pages/IntegrationsPage.tsx` |
| Frontend detail | `pages/IntegrationDetailPage.tsx`, `components/IntegrationBrand.tsx`, `utils/integrationMeta.ts` |
| Styles | `index.css` (reuse hire/brief-section tokens) |
| Tests | `tests/unit/connectors/`, `tests/integration/connectors/` |

## Auth implementation

**OAuth2:** `POST .../oauth/start` → provider → `GET .../oauth/callback` → redirect to detail page.

**Manual:** full form on detail page (dev banner); never hide behind a fold on the index.

## Done when

- CONNECTORS_SPEC §11 satisfied for this type.
- Detail page at `/{workspace}/integrations/{connector_type}` connects, health-checks, disconnects.
- Index page only links out — no inline setup.
- pytest green; manual browser check documented.

## Hand off

- **Architect** — new `connector_type`, schema change, gate gap.
- **Product** — copy or acceptance unclear.
