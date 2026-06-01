# Pidgin Company Service Integration Spec

## 1. Purpose

Pidgin enables companies to deploy AI agents as reachable, accountable participants in the organization without creating a full SaaS account for every agent in every company system.

Instead of requiring accounts like:

```text
jane@company.com in Gmail
Jane in Slack
Jane in Jira
Jane in Confluence
Jane in NetSuite
```

Pidgin connects to company services through a small number of approved **integration accounts**, **bots**, **apps**, or **service accounts**.

Pidgin then manages virtual agent identities, such as Jane, on top of those integrations.

---

# 2. Core model

Pidgin separates three concepts:

```text
Technical identity:
The real account, app, bot, token, or service account used to access a company system.

Virtual agent identity:
The AI agent managed by Pidgin, such as Jane, the AI Accounting Agent.

Attribution:
The visible and auditable record that Jane performed the work via Pidgin, possibly requested or approved by a human.
```

Example:

```text
Target system sees:
Pidgin Jira Connector

Company users see:
Jane, AI Accounting Agent via Pidgin

Pidgin audit log records:
Jane acted through Pidgin, requested by Nitay, approved by policy or human approval.
```

---

# 3. Integration principle

The company admin supplies **connector access**, not **agent accounts**.

```text
Company provides:
- ai@company.com mailbox or routing rule
- Pidgin Slack app installation
- Google Workspace / Microsoft 365 integration
- Jira / Confluence connector account or app
- optional ERP / CRM / accounting-system service accounts

Pidgin provides:
- agent identities
- routing
- permissions
- approval policies
- audit logs
- cross-system context
- per-agent attribution
```

This allows many AI agents to operate through a controlled set of company-approved integrations.

---

# 4. Required integrations

## 4.1 Email integration

### Purpose

Allow employees, vendors, customers, and systems to communicate with Pidgin agents through email.

### Company-provided access

The company admin provides one of the following:

```text
ai@company.com mailbox
shared mailbox
Google Workspace group
email alias
catch-all routing rule
inbound mail forwarding rule
SMTP/IMAP access
Gmail API / Microsoft Graph access
```

### Routing model

Pidgin supports routed email addresses:

```text
ai+jane@company.com
ai+accounting@company.com
ai+legal@company.com
ai+research@company.com
ai+invoice-approval@company.com
```

Pidgin parses the address suffix and routes the message to the correct agent, team, workflow, or context.

Example:

```text
To: ai+jane@company.com
Subject: Reconcile April invoices
```

Pidgin interprets:

```json
{
  "channel": "email",
  "agent": "jane",
  "sender": "nitay@company.com",
  "intent": "reconcile_invoices",
  "context": "email_thread"
}
```

### Outbound email

Pidgin can send emails using the company-provided mailbox.

Example:

```text
From: Pidgin <ai@company.com>
Reply-To: ai+jane@company.com

Hi Dana,

Jane, the AI Accounting Agent, reviewed the invoice and found one missing PO number.
```

### Key requirement

Jane does not need her own email account. Jane is reachable through email routing and represented through Pidgin attribution.

---

## 4.2 Slack integration

### Purpose

Allow employees to communicate with agents from Slack.

### Company-provided access

The company admin installs the Pidgin Slack app.

```text
Real Slack identity:
@Pidgin

Virtual agents:
Jane, Max, Otto, Legal, Research, Ops
```

### MVP mode: one Slack bot, many agents

Employees address agents through the Pidgin bot:

```text
@Pidgin jane, check this invoice
@Pidgin ask legal to review this clause
@Pidgin accounting, summarize unpaid vendors
```

Pidgin parses the message, identifies the target agent, and routes the task internally.

Response example:

```text
Jane · AI Accounting Agent via Pidgin

I found 7 unpaid vendor invoices. 3 require approval.
```

### Advanced mode: Pidgin-managed Slack agent bots

For high-usage agents, Pidgin may create or manage dedicated Slack bot presences:

```text
@Jane Accounting
@Max Sales
@Otto Ops
```

These bots are still centrally managed by Pidgin.

### Key requirement

Slack identity can work in two ways:

```text
MVP:
One real Slack bot: @Pidgin
Many virtual agents behind it

Advanced:
Pidgin-managed Slack bot presences for selected agents
```

The admin should not need to manually create or manage a separate Slack user for every AI agent.

---

## 4.3 Google Workspace / Microsoft 365 integration

### Purpose

Allow agents to read, draft, summarize, and create work across company productivity systems.

### Company-provided access

The company admin connects Pidgin through one or more of:

```text
OAuth app authorization
admin-approved marketplace app
service account
domain-wide delegation
shared mailbox access
Microsoft Graph app registration
Google Workspace app authorization
```

### Services covered

For Google Workspace:

```text
Gmail
Google Drive
Google Docs
Google Sheets
Google Calendar
Google Groups
```

For Microsoft 365:

```text
Outlook
OneDrive
SharePoint
Teams
Word files
Excel files
PowerPoint files
Calendar
```

### Example permissions for Jane

Jane, the AI Accounting Agent, might receive:

```text
Read:
- invoice folders
- vendor records
- accounting spreadsheets
- relevant email threads

Write:
- draft emails
- draft reports
- create spreadsheet summaries
- create internal notes

Requires approval:
- send external emails
- share files externally
- modify official accounting records
```

### Key requirement

Pidgin should support least-privilege access. Jane should not inherit full company-wide permissions just because Pidgin is connected.

Pidgin must map company-level integration access into per-agent permissions.

---

## 4.4 Jira / Confluence integration

### Purpose

Allow agents to interact with tickets, projects, documentation, decisions, and internal knowledge.

### Company-provided access

The company admin provides one of:

```text
Atlassian app installation
OAuth connection
API token
service account
bot user
```

Example technical identity:

```text
pidgin@company.com
```

### Jira actions

Pidgin agents may be allowed to:

```text
read issues
summarize issues
create issues
comment on issues
update issue fields
link related issues
suggest assignees
generate status reports
```

Example Jira comment:

```text
Jane · AI Accounting Agent via Pidgin

I checked the April vendor invoices. Three need approval:
- Acme Ltd — $4,200
- BlueOps — $1,150
- OfficeCo — $780

Requested by: Nitay
Run ID: pg_8f31
```

### Confluence actions

Pidgin agents may be allowed to:

```text
read pages
search internal documentation
draft pages
summarize spaces
comment on pages
prepare meeting notes
maintain team knowledge bases
```

Example Confluence attribution:

```text
Draft prepared by Jane, AI Accounting Agent via Pidgin.

Source: April invoices folder.
Human owner: Nitay.
Audit log: pg_8f31
```

### Key requirement

The target system may only see the Pidgin connector account, but the content and Pidgin audit log must clearly identify the virtual agent, requester, and approval status.

---

## 4.5 ERP / CRM / accounting-system integrations

### Purpose

Allow role-specific agents to work with business systems such as finance, sales, support, HR, and operations tools.

### Example systems

```text
NetSuite
QuickBooks
SAP
Priority
Salesforce
HubSpot
Zendesk
Monday
Linear
GitHub
GitLab
Stripe
Notion
Airtable
```

### Company-provided access

The company admin provides system-specific access, usually through:

```text
API key
OAuth app
service account
read-only user
limited-scope integration user
webhook
export/import permission
```

### Example: Jane, accounting agent

Jane may need access to:

```text
Accounting system:
- read invoices
- read vendors
- read payment status
- export reports

Google Drive / SharePoint:
- read invoice folders
- read accounting files

Email:
- draft vendor emails
- receive invoice-related requests

Jira:
- create finance tasks
- comment on finance tickets

Confluence:
- draft monthly accounting summaries
```

### Risk-based permissions

Low-risk actions may be automatic:

```text
read invoice
summarize vendor status
draft email
create internal task
comment in Slack
```

Higher-risk actions require approval:

```text
send external email
change vendor information
create payment batch
share files externally
update official records
```

Blocked actions:

```text
send payments
approve payments
change bank details
delete financial records
modify audit logs
```

---

# 5. Agent identity object

Pidgin should model every agent as a virtual identity.

Example:

```json
{
  "agent_id": "jane",
  "display_name": "Jane",
  "role": "AI Accounting Agent",
  "handle": "jane",
  "human_owner": "finance-lead@company.com",
  "channels": {
    "email": {
      "address": "ai+jane@company.com"
    },
    "slack": {
      "mode": "virtual_agent",
      "primary_bot": "@Pidgin",
      "dedicated_bot": "@Jane Accounting"
    }
  },
  "connectors": {
    "gmail": "pidgin-google-workspace-connector",
    "drive": "pidgin-google-workspace-connector",
    "jira": "pidgin-atlassian-connector",
    "confluence": "pidgin-atlassian-connector",
    "accounting": "pidgin-accounting-readonly-connector"
  },
  "permissions": {
    "can_read": [
      "invoices",
      "vendors",
      "accounting_reports",
      "finance_jira_project"
    ],
    "can_write": [
      "draft_emails",
      "jira_comments",
      "confluence_drafts",
      "slack_replies"
    ],
    "requires_approval": [
      "external_emails",
      "payment_files",
      "vendor_record_changes"
    ],
    "blocked": [
      "send_payments",
      "approve_payments",
      "change_bank_details",
      "delete_financial_records"
    ]
  }
}
```

---

# 6. Attribution and audit requirements

Every Pidgin action must preserve four identities:

```text
Technical actor:
The real account, app, bot, or service account used.

Virtual actor:
The AI agent, such as Jane.

Requester:
The human, workflow, or system that asked the agent to act.

Approver:
The person or policy that authorized the action.
```

Example audit record:

```json
{
  "run_id": "pg_8f31",
  "technical_actor": "pidgin-jira-connector",
  "virtual_actor": "jane",
  "virtual_actor_role": "AI Accounting Agent",
  "requester": "nitay@company.com",
  "approver": "auto-policy:low-risk-accounting-comments",
  "target_system": "jira",
  "action": "comment",
  "target": "FIN-123",
  "timestamp": "2026-05-25T20:30:00Z"
}
```

This allows the company to answer:

```text
Who technically performed the action?
Pidgin.

Which AI agent performed the work?
Jane.

Who requested it?
Nitay.

Who approved it?
A human or policy.

Where is the full audit trail?
Pidgin.
```

### Trust label and policy decision

In addition to the four identities above, every audit record carries a `trust_label` (how the inbound was classified — `internal-authenticated`, `external-verified`, `external-unverified`, or `untrusted-content`) and a `policy_decision` (how Pidgin handled it — `accepted_as_instruction`, `routed_to_inbox`, `quarantined`, `auto_approved`, `awaiting_human_approval`, or `refused_by_policy`).

Together these answer not only *who* acted, but also *why the action was allowed to happen*. The full model — principals, trust labels, invocation policy derived from the hierarchy recipe, and instructions-vs-data separation — is defined in [SECURITY_SPEC.md](SECURITY_SPEC.md).

---

# 7. Admin onboarding flow

## Step 1 — Connect communication channels

Admin connects:

```text
Email mailbox / route
Slack workspace app
Optional Teams integration
```

This allows employees to talk to agents.

## Step 2 — Connect work systems

Admin connects:

```text
Google Workspace / Microsoft 365
Jira / Confluence
CRM
ERP
Accounting system
GitHub / GitLab
Support tools
```

This allows agents to perform work.

## Step 3 — Define agents

Admin creates virtual agents:

```text
Jane — Accounting
Max — Sales
Otto — Operations
Lex — Legal
Rex — Research
```

Each agent gets:

```text
name
role
handle
owner
default channels
connected tools
permission profile
approval policy
```

## Step 4 — Define access policies

Admin configures:

```text
what each agent can read
what each agent can write
what requires approval
what is blocked
who owns the agent
who can invoke the agent
where the audit log is stored
```

## Step 5 — Deploy to employees

Employees can now interact with agents through:

```text
email
Slack
business tools
internal workflows
```

Example:

```text
Email:
ai+jane@company.com

Slack:
@Pidgin jane, check this invoice

Jira:
Jane via Pidgin comments on finance tickets

Confluence:
Jane via Pidgin drafts accounting summaries
```

---

# 8. Minimum viable integration set

For an MVP, Pidgin should require only:

```text
1. One email identity:
   ai@company.com

2. One Slack app:
   @Pidgin

3. One document integration:
   Google Drive or Microsoft OneDrive / SharePoint

4. One task/documentation integration:
   Jira / Confluence, Linear, Notion, or Monday

5. Pidgin audit log:
   internal system of record
```

With this, Pidgin can already support:

```text
agent communication
task creation
document reading
draft generation
Slack interaction
email interaction
basic auditability
```

---

# 9. Later enterprise integrations

After MVP, Pidgin can add:

```text
SCIM / directory sync
SAML / SSO
RBAC groups
DLP integration
SIEM export
audit log export
approval workflows
data retention policies
eDiscovery support
dedicated Slack agent bots
Teams bot identities
advanced ERP / CRM connectors
```

This moves Pidgin from a collaboration layer into a full enterprise AI workforce identity layer.

---

# 10. Spec summary

```text
Pidgin integrates with company services through a small number of admin-approved connector accounts, apps, bots, and service accounts.

These integrations provide the real technical access to systems such as email, Slack, Google Workspace, Microsoft 365, Jira, Confluence, ERP, CRM, and accounting tools.

On top of these integrations, Pidgin manages virtual AI agent identities. Employees can contact agents through routed email addresses, Slack commands, or dedicated Pidgin-managed bot presences. When agents act inside company systems, the action is technically performed by a Pidgin connector but semantically attributed to the relevant agent.

This architecture avoids the need to create full SaaS user accounts for every AI agent, while preserving clear permissions, human ownership, approval policies, and audit trails.
```

The short product line:

```text
Pidgin connects once to company tools, then gives every AI agent a governed identity across them.
```

Related specs: [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md), [SCHEMA_SPEC.md](SCHEMA_SPEC.md), [TECH_STACK_SPEC.md](TECH_STACK_SPEC.md), [CONNECTORS_SPEC.md](CONNECTORS_SPEC.md) (implementation contract).
