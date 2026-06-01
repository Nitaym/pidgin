# Role Recipe Spec (MVP)

Defines the JSON bundle format for **role recipes** consumed by the Pidgin runtime at hire time. Hierarchy recipes are out of scope for MVP.

**Related:** [PRODUCT_SPEC.md](PRODUCT_SPEC.md) §Recipes, [SCHEMA_SPEC.md](SCHEMA_SPEC.md) (`ai_employee_recipe_snapshots`), [SECURITY_SPEC.md](SECURITY_SPEC.md) (permission profiles).

---

## 1. Bundle lifecycle

1. Operator selects a role recipe (bundled JSON file or marketplace URL).
2. Runtime loads and validates the bundle.
3. Runtime computes `bundle_sha256 = SHA256(canonical_json)`.
4. Runtime inserts an immutable row in `ai_employee_recipe_snapshots` and links `ai_employees.recipe_snapshot_id`.
5. Upgrades create a **new** snapshot row; old snapshots are never edited.

Marketplace is a separate app. MVP ships bundled role recipes:

| File | `recipe_id` |
|------|-------------|
| `recipes/support-agent-v0.1.json` | `support-agent` |
| `recipes/executive-assistant-v0.1.json` | `executive-assistant` |

---

## 2. JSON schema (role recipe v0.1)

Top-level object:

| Field | Type | Required | Notes |
|---|---|---|---|
| `recipe_id` | string | yes | Stable slug, kebab-case (e.g. `support-agent`) |
| `version` | string | yes | Semver (e.g. `0.1.0`) |
| `display_name` | string | yes | Default agent display name at hire |
| `role_title` | string | yes | Job title shown in UI |
| `description` | string | no | Human-readable summary |
| `permissions` | object | yes | See §3 |
| `default_channels` | string[] | no | Suggested rooms/channels (e.g. `#support`) |
| `system_prompt_template` | string | yes | Jinja-style `{{display_name}}`, `{{role_title}}` |
| `default_job_requirements` | object | no | Pre-fill for hire wizard **Job requirements** (see §2.1) |
| `default_ideal_candidate` | object | no | Pre-fill for **Ideal candidate profile** (see §2.1) |
| `tools` | string[] | no | Tool IDs enabled for this role (empty in MVP stub) |

Examples: `recipes/support-agent-v0.1.json`, `recipes/executive-assistant-v0.1.json`.

### 2.1 Hire wizard pre-fill objects

Bundled Pidgin role templates may include defaults that seed the hire wizard ([MVP_USER_STORIES.md](MVP_USER_STORIES.md) US-6). Values map directly to `ai_employees.hire_customization_json` ([SCHEMA_SPEC.md](SCHEMA_SPEC.md) §7.1).

**`default_job_requirements`:**

| Field | Type | Notes |
|---|---|---|
| `mission` | string | Primary purpose |
| `responsibilities` | string[] | Ordered bullet list |
| `out_of_scope` | string[] | Explicit boundaries |

**`default_ideal_candidate`:**

| Field | Type | Notes |
|---|---|---|
| `tone` | string | Communication style |
| `decision_framework` | string | How the agent should decide |
| `escalation_rules` | string | When and how to escalate |

Example fragment:

```json
{
  "default_job_requirements": {
    "mission": "Resolve customer issues quickly and empathetically.",
    "responsibilities": [
      "Triage inbound support messages",
      "Draft replies for operator approval"
    ],
    "out_of_scope": [
      "Billing refunds without approval",
      "Legal commitments"
    ]
  },
  "default_ideal_candidate": {
    "tone": "Professional, warm, concise",
    "decision_framework": "Prioritize customer impact, then SLA, then effort",
    "escalation_rules": "Escalate billing disputes and angry VIPs to the owner"
  }
}
```

Omitted objects or fields mean empty wizard sections. Workspace **Your role templates** store the same content in versioned Markdown files instead of JSON ([SCHEMA_SPEC.md](SCHEMA_SPEC.md) §4.1.1).

---

## 3. Permissions object

Maps to runtime `PermissionProfile` (see `src/pidgin/types/models.py`). Values are **action type strings** from [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) (14 actions).

| Field | Type | Default | Meaning |
|---|---|---|---|
| `can_read` | string[] | `[]` | Read actions allowed when trust permits |
| `can_write` | string[] | `[]` | Write actions allowed when trust permits |
| `requires_approval` | string[] | `[]` | Staged for human approval |
| `blocked` | string[] | `[]` | Always refused by policy gate |

Validation rules:

- Every listed action must be one of the 14 locked action types.
- An action must not appear in more than one bucket (`blocked` wins over `requires_approval` over read/write lists at resolve time).
- Empty `can_read` / `can_write` means "no extra restriction" for that bucket (gate still applies trust rules).

At hire time, `ai_employees.permission_overrides_json` may merge on top of recipe permissions (company customization). Resolved profile is computed at gate time, not stored on the employee row.

---

## 4. Canonical JSON and checksum

`bundle_sha256` is SHA-256 hex of UTF-8 bytes of:

```python
json.dumps(bundle_dict, sort_keys=True, separators=(",", ":"))
```

The full canonical JSON is stored in `ai_employee_recipe_snapshots.bundle_json`. `bundle_sha256` is a cache column (recomputable).

---

## 5. Snapshot row mapping

| DB column | Source |
|---|---|
| `recipe_id` | `recipe_id` |
| `recipe_version` | `version` |
| `bundle_json` | canonical JSON string |
| `bundle_sha256` | §4 |
| `source_url` | File path or marketplace URL at load time |
| `fetched_at` | UTC ISO timestamp at hire |
| `ai_employee_id` | Hired agent ULID |

---

## 6. Immutability

- Snapshots are append-only. No `UPDATE` on `ai_employee_recipe_snapshots`.
- Recipe library may publish new semver versions; hired agents keep their snapshot unless explicitly upgraded (future).

---

## 7. MVP omissions

- Interview scenarios, onboarding checklists, multi-agent decomposition
- Hierarchy recipes
- JSON Schema file on disk (Pydantic validation in `src/pidgin/recipes/` for now)
- Marketplace fetch/auth

---

## 8. Open decisions

| Topic | Recommendation |
|---|---|
| Handle default | Derive from hired `display_name`: lowercased, non-alphanumeric → `-` |
| `display_name` at hire | Recipe JSON `display_name` is a catalog default only; operator sets the live name when hiring (e.g. personal name). Prompts use `{{display_name}}` from the hired employee. |
| Initial employee status | `draft` until interview completes |
| Upgrade flow | New snapshot + pointer update (Phase 4+) |
| Hire pre-fill | `default_job_requirements` / `default_ideal_candidate` optional; recipes writer adds when updating bundled templates (PID-8) |
