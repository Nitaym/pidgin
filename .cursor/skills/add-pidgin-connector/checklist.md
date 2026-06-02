# Connector implementation checklist (detail)

Use with [SKILL.md](SKILL.md). Authority: [specs/CONNECTORS_SPEC.md](../../specs/CONNECTORS_SPEC.md).

## Backend package

- `ConnectorProtocol` implementation with `connector_type` class constant
- `metadata()` returns capabilities: ingress, read, draft, execute, watch
- `health_check()` updates installation status on failure
- Async I/O; use official SDK from TECH_STACK_SPEC §7
- Errors map to `GateOutcome.FAILED` + structured log, not silent swallow

## Registry

- Register at app startup (`api/app.py` lifespan or connectors `__init__.py`)
- `resolve_resource(uri)` picks installation when multiple same-type installs exist (use config_json default or explicit installation_id in URI query — document in §11)

## Ingress

- Verify webhook signatures (Slack signing secret, etc.)
- Idempotency: dedupe on provider event ID stored in `payload_json.raw_ref` or small dedupe table if needed (note in PR if added)
- Create/link `rooms` row with correct `modality` + `external_system_id`
- Routing tests for virtual agent handle extraction

## Egress / actions

- `say` on Slack/Gmail maps to reply in **source** channel from turn context
- `post` targets different resource URI — gate checks `can_write`
- `read` returns text suitable for LLM (size cap ~32 KB per AGENT_RUNTIME_SPEC §5.3)
- `execute` for send/post/create — default staging if Phase 3 approvals not wired (return clear error, do not bypass gate)

## API routes

- Session-authenticated CRUD on `/integrations`
- OAuth callback is unauthenticated but validates `state` nonce tied to workspace + user
- Never return full `credentials_json` in GET responses — mask tokens

## Frontend

- Route: `/{workspace}/integrations/{connector_type}` — shared `IntegrationDetailPage`
- Index: `IntegrationsPage` — catalog grid only; no inline connect UI
- Add `integrationMeta.ts` entry (tagline, accent, monogram)
- Reuse hire patterns: `brief-section`, `template-grid`, `eyebrow`, `review-template`
- OAuth + manual on detail page via tabs when both supported — never collapsible on index
- After OAuth redirect lands on detail page

## Tests

Minimum:

1. Resource URI parse round-trip
2. Ingress payload normalization golden file
3. Webhook signature reject/accept
4. Registry resolves mock installation
5. (Optional) VCR recorded HTTP — prefer mock SDK clients for unit tests

## Manual smoke (required)

Document in PR:

1. Open Integrations page
2. Connect via OAuth (or manual dev path)
3. Health check passes
4. Trigger one inbound event (Slack message, test email, etc.)
5. Agent turn runs (stub LLM OK) and audit row shows correct `technical_actor`
