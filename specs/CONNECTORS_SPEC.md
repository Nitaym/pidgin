# Pidgin Connectors Spec

Implementation contract for workspace integrations. Product model (virtual agents, attribution, permission buckets) lives in [INTEGRATION_WOFKLOW.md](INTEGRATION_WOFKLOW.md). Runtime placement (triggers, actions, gate) lives in [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) §9.4.

**Scope:** How to add and operate connectors in the runtime + admin UI. **Out of scope:** Marketplace recipe fields, SSO/SCIM, credential encryption (post-MVP).

---

## 1. Summary

```text
One connector_installations row per workspace install.
Each connector_type implements ingress (→ inbound_events) and egress (read / draft / execute / post / watch).
Agents never hold credentials — the connector layer does, keyed by installation id.
Every side effect goes through gate() → agent_action_log with technical_actor = connector id.
```

**MVP build order (locked):**

| Order | `connector_type` | Primary capability |
| --- | --- | --- |
| 0 | `pidgin_chat` | In-process chat (refactor existing `services/chat.py`) |
| 1 | `slack` | `@Pidgin <agent>, …` ingress + thread reply egress |
| 2 | `gmail` | Inbound email + draft/send egress |
| 3 | `google_drive` | Read files/folders (agent `read` action) |
| 4 | `google_meet` | Read upcoming meetings; draft calendar holds (execute gated) |
| 5 | `zoom` | Read meetings; create/update via API (execute gated) |

---

## 2. Storage

Uses existing `connector_installations` ([SCHEMA_SPEC.md](SCHEMA_SPEC.md) §6):

| Column | Purpose |
| --- | --- |
| `connector_type` | Stable slug — see §3 |
| `display_name` | Operator label, e.g. "Acme Slack" |
| `credentials_json` | OAuth tokens, API keys, bot tokens (plaintext MVP) |
| `config_json` | Non-secret: team IDs, webhook URLs, routing defaults |
| `status` | `active` \| `disabled` \| `errored` |

**One active installation per `(connector_type, display_name)`** per workspace. Multiple Gmail installs are allowed if `display_name` differs (e.g. shared mailbox vs personal).

### 2.1 `credentials_json` shape (by auth mode)

**OAuth (refreshable):**

```json
{
  "auth_mode": "oauth2",
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": "2026-06-02T12:00:00Z",
  "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
  "provider_account_id": "..."
}
```

**Manual (operator paste):**

```json
{
  "auth_mode": "manual",
  "fields": {
    "bot_token": "xoxb-...",
    "signing_secret": "..."
  }
}
```

Field names are per-connector — see §8. Manual mode is **dev / fallback only** in UI copy unless the connector row in §8 marks it production-supported.

---

## 3. Connector types

| `connector_type` | Auth modes | Ingress triggers | Egress actions |
| --- | --- | --- | --- |
| `pidgin_chat` | none | `direct_address`, `channel_activity` | `say`, `post`, `read` |
| `slack` | oauth2, manual | `direct_address` | `say`, `post`, `read`, `watch` |
| `gmail` | oauth2, manual | `inbound_external` | `read`, `draft`, `execute` |
| `google_drive` | oauth2, manual | — (egress only MVP) | `read`, `draft` |
| `google_meet` | oauth2 | — | `read`, `draft`, `execute` |
| `zoom` | oauth2, manual | — | `read`, `draft`, `execute` |

Shared Google OAuth app may back `gmail`, `google_drive`, and `google_meet` — one installation row per type, tokens may share refresh via same Google account connect flow.

---

## 4. Resource URIs

Actions reference resources with a typed URI string:

```text
<prefix>:<kind>/<id>[?<query>]
```

| Prefix | Examples |
| --- | --- |
| `pidgin_chat` | `pidgin_chat:conversation/<ulid>`, `pidgin_chat:room/<ulid>` |
| `slack` | `slack:channel/C0123`, `slack:thread/C0123:1234567890.123456` |
| `gmail` | `gmail:thread/<id>`, `gmail:message/<id>` |
| `google_drive` | `gdrive:file/<id>`, `gdrive:folder/<id>` |
| `google_meet` | `gmeet:event/<id>`, `gmeet:calendar/primary` |
| `zoom` | `zoom:meeting/<id>`, `zoom:user/me` |

Parser lives in `src/pidgin/connectors/resources.py`. Unknown prefix → gate refuses with `refused`.

---

## 5. Python module contract

Each connector is a package under `src/pidgin/connectors/<connector_type>/`:

```
connectors/
  base.py              # ConnectorProtocol, ConnectorRegistry
  resources.py         # parse_resource_uri()
  pidgin_chat/
    __init__.py        # register()
    connector.py       # egress
    ingress.py         # optional — pidgin uses API layer
  slack/
    connector.py
    ingress.py         # webhook handler
    oauth.py
  ...
```

### 5.1 `ConnectorProtocol` (egress)

```python
class ConnectorProtocol(Protocol):
    connector_type: str
    installation_id: str

    def metadata(self) -> ConnectorMetadata: ...

    async def read(
        self, resource: ResourceUri, *, principal: PrincipalContext
    ) -> ReadResult: ...

    async def write(
        self,
        resource: ResourceUri,
        payload: WritePayload,
        *,
        principal: PrincipalContext,
        mode: Literal["draft", "execute"],
    ) -> WriteResult: ...

    async def subscribe(
        self, resource: ResourceUri, *, callback: WatcherCallback
    ) -> str: ...  # watcher handle

    async def unsubscribe(self, handle: str) -> None: ...

    async def health_check(self) -> HealthStatus: ...
```

- **`write(..., mode="draft")`** maps to action `draft`; **`mode="execute"`** maps to action `execute`.
- **`post`** action resolves target channel to a resource URI and calls `write` on the owning connector.
- All methods are invoked **only after** `gate()` accepts the action.

### 5.2 Ingress adapter

Ingress code **never** runs turns directly. It:

1. Resolves or creates `principals` (Slack user, email From, etc.)
2. Classifies `trust_label` ([SECURITY_SPEC.md](SECURITY_SPEC.md))
3. Routes to target `ai_employee_id` (handle in text, `ai+handle@` alias, room membership)
4. Inserts `inbound_events` with normalized payload (§6)
5. Calls `run_once()` or leaves for scheduler

### 5.3 Registry

```python
registry.get(installation_id) -> ConnectorProtocol
registry.for_type(connector_type) -> list[ConnectorProtocol]  # active only
registry.resolve_resource(uri) -> (installation_id, ConnectorProtocol)
```

Recipe `permissions.can_read` / `can_write` buckets use **logical resource names** (e.g. `finance_jira_project`) mapped in `config_json` per installation — not raw URIs. Mapping table format TBD per connector in §8.

---

## 6. Normalized ingress payload

Every connector must populate `inbound_events.payload_json` with at least:

```json
{
  "connector_type": "slack",
  "connector_installation_id": "01J...",
  "external_channel_id": "C0123",
  "external_thread_id": "1234567890.123456",
  "message_text": "...",
  "raw_ref": { "ts": "...", "team_id": "..." },
  "room_id": "01J...",
  "conversation_id": "01J..."
}
```

Optional keys: `attachment_refs[]`, `mentioned_handles[]`, `subject` (email).

Runtime turn builder uses these keys — do not invent parallel shapes per connector.

---

## 7. Admin API

Base: `/api/workspaces/{workspace_id}/integrations`

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/integrations` | List installations + status + capabilities |
| GET | `/integrations/catalog` | Supported types, auth modes, required scopes |
| POST | `/integrations/{connector_type}/oauth/start` | Returns `{ authorization_url, state }` |
| GET | `/integrations/oauth/callback` | Global callback; exchanges code; redirects to UI |
| POST | `/integrations/{connector_type}/manual` | Body: `{ display_name, fields: {...} }` |
| POST | `/integrations/{id}/health` | Run health_check; update status |
| PATCH | `/integrations/{id}` | Enable/disable, update config_json |
| DELETE | `/integrations/{id}` | Disable + clear credentials (soft delete optional) |

**Webhook ingress (no session cookie):**

| Route | Connector |
| --- | --- |
| `POST /hooks/slack/events` | Slack Events API |
| `POST /hooks/gmail/push` | Gmail Pub/Sub push (post-MVP polling OK for MVP) |

Webhook routes verify signatures using secrets from `credentials_json` / env.

---

## 8. Frontend — Integrations UI

Follow [UI_DESIGN_GUIDE.md](UI_DESIGN_GUIDE.md) and match the hire wizard visual system (`brief-section`, `template-grid`, `eyebrow`, `hire-page-main`).

### Routes

| Route | Component | Purpose |
| --- | --- | --- |
| `/{workspace}/integrations` | `IntegrationsPage` | Catalog grid — links only, no inline connect |
| `/{workspace}/integrations/{connector_type}` | `IntegrationDetailPage` | Dedicated setup page per integration |

Legacy `/{workspace}/settings/integrations` redirects to `/integrations`.

### Index page (`IntegrationsPage`)

- Grid of catalog cards (like hire template picker)
- Each card: brand monogram, description, capability chips, connection status, “Configure →”
- **No** collapsible panels, **no** inline OAuth/manual forms

### Detail page (`IntegrationDetailPage`)

Shared shell for every `connector_type`. Sections:

1. **Hero** — name, tagline, description, capabilities
2. **Connect** — OAuth button and/or manual credential fields (always visible)
   - When both auth modes supported: `.tabs` toggle (OAuth | Manual setup), not an accordion
3. **Manage** — when connected: status, health check, disconnect

Add per-type copy/colors in `src/frontend/src/utils/integrationMeta.ts`.

OAuth callback redirects to `/{workspace}/integrations/{connector_type}`.

Copy uses "integration" / "connection", not "connector" in user-facing strings.

---

## 9. Attribution

`agent_action_log.technical_actor` = `connector_installations.id` or stable slug `slack:01J...`.

Virtual actor fields unchanged ([INTEGRATION_WOFKLOW.md](INTEGRATION_WOFKLOW.md) §6). Slack/Jira comments prepend virtual agent line in **content**, not only in Pidgin audit.

---

## 10. Gate and approvals

| Action | Slack / Gmail external send | Drive read |
| --- | --- | --- |
| `read` | Gate + recipe `can_read` | Gate + `can_read` |
| `draft` | Gate + `can_write` | Gate + `can_write` |
| `execute` | **`requires_approval` default** until Phase 3 inbox wired | Same for file create/share |

Ingress from `external-unverified` cannot originate `execute` in the same turn ([SECURITY_SPEC.md](SECURITY_SPEC.md) §6).

---

## 11. Per-connector notes

### 11.1 Slack (`slack`)

- **Libraries:** `slack-sdk`, `slack-bolt` ([TECH_STACK_SPEC.md](TECH_STACK_SPEC.md))
- **OAuth:** workspace install → bot token + team_id in credentials
- **Manual:** `bot_token`, `signing_secret`, `app_token` (socket mode dev)
- **Ingress:** Events API `app_mention`, `message.im`; parse `@Pidgin <handle>, …`
- **Egress `say`:** `chat.postMessage` in source channel; prefix attribution block
- **Principal:** upsert on `slack_user_id`

### 11.2 Gmail (`gmail`)

- **Libraries:** `google-api-python-client`, `google-auth`
- **OAuth scopes (MVP):** `gmail.readonly`, `gmail.compose`, `gmail.send` (send gated)
- **Manual (dev):** app password + IMAP host — flagged deprecated in UI
- **Ingress:** polling or webhook; trigger `inbound_external`; route `ai+<handle>@domain`
- **Principal:** upsert on `email_address`

### 11.3 Google Drive (`google_drive`)

- **OAuth scopes:** `drive.readonly` for reads; full `drive` for writes. Reads
  and writes mint separately-scoped tokens, so both scopes must be authorised for
  domain-wide delegation.
- **Manual:** service account JSON + delegated user email (domain-wide delegation)
- **Egress `read`:** exports Google Docs/Sheets/Slides → text/CSV and downloads
  other files via `alt=media`; folder reads list children as `gdrive:file/<id>`
  lines. Output capped at ~32 KB ([AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) §5.3).
- **Egress `execute` (write):** creates **new** content only — a file
  (`gdrive:folder/<id>` + `name` + `content`) or a subfolder (`kind: folder`).
  Surfaced via the `execute` tool, gated by `can_write`. **Creation is additive
  and not owner-approved.** Editing or deleting an existing file is a gated
  mutation — the connector refuses a file-target write until the Phase 3 approval
  inbox (§10) is wired, so no ungated edit/delete path exists.
- **Resource prefix:** URIs use `gdrive:` (§4); the registry maps it to the
  `google_drive` connector_type via `connector_type_for_prefix()` in `resources.py`.

**Implementation status:** Manual (service account) auth is wired first — the
catalog advertises `auth_modes: ["manual"]` until the shared Google OAuth flow
(reused by `gmail` / `google_meet`) lands in `start_oauth` / `complete_oauth`.
Service-account tokens are minted by signing an RS256 JWT (`PyJWT[crypto]`) and
exchanging it at Google's `jwt-bearer` token endpoint — no token-refresh state.

### 11.4 Google Meet (`google_meet`)

- **OAuth scopes:** `calendar.readonly`, `calendar.events` (execute gated)
- **Manual:** not supported MVP
- **Egress:** read upcoming events linked to Meet conferences; draft = calendar hold

### 11.5 Zoom (`zoom`)

- **OAuth:** standard Zoom OAuth app
- **Manual:** Server-to-Server OAuth account ID + client ID + secret
- **Egress:** read meetings; draft/create meeting via API (execute gated)

---

## 12. Testing

Each connector ships:

| Layer | Location |
| --- | --- |
| Unit | `tests/unit/connectors/test_<type>.py` — URI parse, payload normalize, signature verify |
| Integration | `tests/integration/connectors/test_<type>.py` — simulated ingress → event row |
| Manual | Integrations UI connect → health green → inject test message (document in PR) |

Use **simulated connector** (in-memory) for turn executor tests before real OAuth ([AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) §9.4).

---

## 13. Dependencies

| Needs | Phase |
| --- | --- |
| Turn executor + action dispatcher | Phase 2.4 |
| `pidgin_chat` refactor | Phase 2.2 / 2I.1 |
| External `execute` / send | Phase 3 approvals (can ship read + ingress earlier) |
| Gate wired | Before any production external write |

---

## Cross-references

- [INTEGRATION_WOFKLOW.md](INTEGRATION_WOFKLOW.md) — product model
- [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) — triggers, actions, §9.4
- [SCHEMA_SPEC.md](SCHEMA_SPEC.md) — `connector_installations`, `principals`, `rooms.modality`
- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) — Phase 2I tasks
- [UI_DESIGN_GUIDE.md](UI_DESIGN_GUIDE.md) — Integrations page
- Project skill: `.cursor/skills/add-pidgin-connector/SKILL.md`
