# AI-Native Workspace -- Product Spec

> **One-liner:** A Slack-like internal workspace where companies hire AI employees, communicate with them by text, voice, calls, and meetings, assign them work, and ask what happened across the company.

> **Positioning:** Slack was built for companies where only humans work. This is the workspace for companies where humans and AI employees work side by side.

> **Short version:** The internal workspace for AI-native companies.

> **Product claim:** Hire AI employees, onboard them, communicate naturally, assign work, and ask what happened across the business.

---

## Table of Contents

1. [Product Vision](#product-vision)
2. [Key Distinctions](#key-distinctions)
3. [Recipes](#recipes)
4. [Core Problem](#core-problem)
5. [Target Users](#target-users)
6. [Core Product Loop](#core-product-loop)
7. [Core Feature Pillars](#core-feature-pillars)
8. [Core Entities](#core-entities)
9. [AI Employee Object](#ai-employee-object)
10. [Security Model](#security-model)
11. [Company Pulse](#company-pulse)
12. [User Flows](#user-flows)
13. [Information Architecture](#information-architecture)
14. [MVP Scope](#mvp-scope)
15. [Success Criteria](#success-criteria)
16. [Competitive Framing](#competitive-framing)
17. [Strategic Moat](#strategic-moat)
18. [Open Decisions](#open-decisions)
19. [Roadmap Tiers](#roadmap-tiers)

---

## Product Vision

Companies are starting to use AI agents as workers, but current tools still assume every worker is human. Agents are usually bolted onto Slack, Jira, Gmail, or CRMs as bots.

This product treats AI agents as **first-class organizational participants** with roles, memory, responsibility, permissions, and accountability.

The product is not just a chatbot, agent framework, or Slack plugin. It is the **communication and operating layer for AI-native companies**.

Unlike generic agent builders that hand you a blank canvas, this product ships with **premade recipes** -- opinionated blueprints for how a company should be organized and how specific human roles should be performed by AI employees.

---

## Key Distinctions

These are the ideas that separate this product from "Slack with bots" or "build your own agent."

| Distinction | Generic agent tools | This product |
|-------------|---------------------|--------------|
| Starting point | Blank prompt + tool list | Premade **recipes** for org structure and roles |
| Unit of value | One agent | A **workforce** -- hierarchy + roles + coordination |
| Role definition | Ad-hoc system prompt | Full **role recipe**: prompts, boundaries, tools, interview, onboarding |
| Company setup | Manual configuration | **Hierarchy recipe** instantiates rooms, reporting lines, workflows |
| Improvement loop | Edit prompt yourself | **Reviewer agent** improves recipes from interview and performance data |
| Trust model | Turn it on and hope | Hire -> interview -> shadow -> approve, baked into every role recipe |

### What "recipe" means

A **recipe** is not a loose template or a snippet. It is a complete, tested, versioned package that can be instantiated into a live workspace. Recipes are the unit of product IP -- curated by the platform, customized by the company, and refined over time.

There are two recipe layers:

1. **Company hierarchy recipes** -- how the org is structured
2. **Role recipes** -- how a specific human job is performed by one or more AI employees

---

## Recipes

### Company Hierarchy Recipes

A hierarchy recipe defines **how a type of company should be organized** when humans and AI employees work together.

It is more than a workspace template. It specifies the operating model:

| Included | Example (SaaS Company Recipe) |
|----------|-------------------------------|
| Org chart | Founder -> CS Lead (human or AI) -> Support Agent, Onboarding Agent |
| Default rooms | `#general`, `#customer-success`, `#product-feedback`, `#incidents` |
| Reporting lines | Support Agent reports to CS Lead; Product Assistant reports to Founder |
| Cross-role workflows | Support escalates product bugs to Product Assistant; CS feeds churn signals to Founder |
| Coordination rules | Who gets @mentioned for what; which decisions require human approval |
| Recommended hires | Suggested role recipes to activate first based on company stage |
| Policies | Default permission posture, approval gates, audit requirements |

**Hierarchy recipes answer:** "If I run a SaaS company (or agency, sales-led org, etc.), what should my AI-augmented team look like on day one?"

Available hierarchy recipes (initial set):

- SaaS / web product
- Sales-led B2B
- Agency / services
- Physical product / ops-heavy
- Technical product company

---

### Role Recipes

A role recipe defines **everything needed for an AI employee (or team of agents) to perform a specific human role**.

It is the full job package -- not just a name and a one-line prompt.

| Component | What it contains |
|-----------|------------------|
| **Role definition** | Title, mission, scope, responsibilities, boundaries, what this role does *not* do |
| **Prompts** | System prompt, behavioral guidelines, tone, decision framework, escalation logic |
| **Agent configuration** | Single agent vs. multi-agent decomposition for one human role (see below) |
| **Tools** | Which integrations the role uses and how (read, draft, execute) |
| **Permissions** | Default access level; what requires human approval |
| **Memory scope** | What organizational context this role retains and references |
| **Rooms** | Which channels the role joins and participates in |
| **Interview scenarios** | Role-specific tests run before hire (e.g. angry customer, ambiguous refund request) |
| **Onboarding checklist** | Shadow-mode tasks, docs to ingest, trial assignments |
| **Example outputs** | Sample messages, drafts, and decisions showing good performance |
| **KPIs / review criteria** | How the reviewer agent evaluates this role over time |

**Role recipes answer:** "If I hire a Customer Success Manager (or Support Agent, Sales Assistant, QA Agent), exactly how should that AI employee behave, what can they do, and how do I know they're ready?"

#### One human role -> one or many agents

A role recipe may instantiate as:

- **Single agent** -- one AI employee covers the full role (e.g. "Maya, Customer Success Agent")
- **Agent team** -- multiple cooperating agents under one human role title (e.g. "Support" = Triage Agent + Response Agent + Escalation Agent)

The recipe defines the decomposition. The user hires the role; the platform resolves the agent topology.

#### Example role recipes (initial set)

| Role Recipe | Primary function |
|-------------|------------------|
| Customer Success Agent | Onboard and retain customers |
| Support Agent | Resolve tickets, triage issues, escalate |
| Sales Assistant | Qualify leads, draft outreach, update CRM |
| Product Assistant | Synthesize feedback, draft specs, track requests |
| QA Agent | Run test scenarios, report bugs, verify fixes |
| Ops Agent | Monitor workflows, flag blockers, coordinate handoffs |
| Engineering Assistant | Triage bugs, draft PRs, summarize code changes |

---

### Recipes vs. Templates vs. Custom

| Layer | What it is | User action |
|-------|------------|-------------|
| **Hierarchy recipe** | Company-type org blueprint | "Create workspace from SaaS recipe" |
| **Role recipe** | Hireable job package | "Hire from Support Agent recipe" |
| **Customization** | Company-specific overrides | Adjust prompts, permissions, tools after hire |
| **Custom role** | Build from scratch | Defer to v0.2+; MVP is recipe-first |

Users start from recipes, then customize. They do not start from a blank agent config.

---

### Recipe Library

Recipes are a **first-class product surface**, not internal config:

- Browsable library of hierarchy and role recipes
- Versioned (recipe v1.2 improves interview scenarios based on aggregate performance)
- Instantiated into live workspaces and AI employees
- Improved by reviewer agent feedback across customers (anonymized patterns)
- Eventually: community-contributed recipes (post-MVP)

---

## Core Problem

| Missing Concept | Why It Matters |
|-----------------|----------------|
| AI employee identity | Agents need names, roles, managers, responsibilities, and status |
| Premade org and role definitions | Founders shouldn't have to invent prompts, hierarchies, and workflows from scratch |
| Hiring and onboarding | Companies need to test, train, and limit agents before trusting them |
| Human-agent communication | Work is not only text; teams use voice, calls, meetings, and screen-share |
| Shared company memory | Agents need organizational context, not isolated personal chat history |
| Task ownership | Conversations need to become structured work with owners and outcomes |
| Permissions and audit | Agent actions need approval gates, limits, and reviewability |
| Company recall | Users should ask what happened today, this week, or this year |

---

## Target Users

| User | Pain |
|------|------|
| Founder / CEO | Too many functions to coordinate; wants leverage from an AI workforce |
| Team lead | Needs to coordinate humans and agents across tasks and decisions |
| Small SaaS company | Needs support, product, sales, and ops capacity without hiring full teams |
| Agency / service company | Repeated workflows and communication-heavy delivery |
| Technical product company | Needs help across support, engineering, product, and customer success |

### Personas (Expanded)

| Persona | Job to Be Done | Success Metric |
|---------|----------------|----------------|
| Founder / CEO | Get leverage across functions without hiring a full team | "I picked the SaaS recipe and had a working AI team in an hour" |
| Team lead | Coordinate humans and agents on shared work | Tasks have clear owners; nothing falls through cracks |
| Ops / admin | Hire, configure, and govern agents safely | Agents pass interview; risky actions require approval |
| Individual contributor | Talk to AI coworkers naturally | Faster than switching between three different tools |

---

## Core Product Loop

1. **Create workspace** -- choose a **hierarchy recipe**: SaaS, web product, sales-led, physical product, agency, etc.
2. **Talk to company operator** -- a chief-of-staff-like AI maps goals, team, gaps, tools, and workflows; recommends which **role recipes** to hire first
3. **Hire AI employees** -- instantiate **role recipes** such as Support, Product, Sales, QA, Ops, Engineering Assistant
4. **Interview and improve** -- run scenarios from the role recipe; reviewer agent improves prompts, tools, and guardrails
5. **Onboard** -- follow the role recipe's onboarding checklist; agents learn docs, join rooms, enter shadow mode
6. **Communicate** -- humans message, voice-note, call, meet with, or screen-share with agents
7. **Assign and govern** -- conversations become tasks; actions require permission, approval, and audit trails
8. **Recall** -- ask "What did I do today?" or "What happened in the company this week?"

---

## Core Feature Pillars

| Pillar | Meaning |
|--------|---------|
| **Hierarchy recipes** | Premade org structures: reporting lines, rooms, workflows, policies, and recommended hires by company type |
| **Role recipes** | Premade job packages: role definition, prompts, tools, permissions, interview, onboarding, and examples |
| Recipe library | Browsable, versioned collection of hierarchy and role recipes |
| Company operator | A CEO/chief-of-staff style setup and routing agent that helps configure the workspace |
| Hire AI employees | Agents are hired from role recipes into real roles with identity, manager, responsibilities, and permissions |
| Interview agents | Candidates are tested with scenarios defined in the role recipe |
| Reviewer agent | Evaluates interviews and improves role recipe prompts, tools, escalation rules, and permissions |
| Onboarding | Agents follow the role recipe's onboarding path: context, rooms, shadow mode, trial tasks |
| AI-first communication | Text, voice notes, calls, meetings, standups, and screen-share with AI coworkers |
| Rooms | Internal spaces where humans and AI employees collaborate and agents can be mentioned |
| Tasks and actions | Conversations become work with buttons: Investigate, Draft, Fix, Review, Execute, Escalate |
| Company Pulse | Ask what happened today/week/year, what changed, what is blocked, and what needs attention |

---

## Core Entities

These are first-class objects, not metadata on chat messages.

| Entity | Purpose | Key Fields |
|--------|---------|------------|
| **Workspace** | Company container | Hierarchy recipe, settings, integrations |
| **Hierarchy Recipe** | Org blueprint | Company type, org chart, rooms, workflows, policies, recommended roles |
| **Role Recipe** | Hireable job package | Definition, prompts, tools, permissions, interview scenarios, onboarding, examples |
| **AI Employee** | Instantiated agent | Role recipe source, name, manager, status, rooms, tools, permissions, memory scope |
| **Human Member** | Real user | Role, permissions, managed agents |
| **Room** | Collaboration space | Members (human + AI), purpose, visibility |
| **Conversation** | Message thread | Participants, modality (text/voice/call/meeting), linked task |
| **Task** | Structured work | Owner, status, source conversation, action buttons, outcome |
| **Action** | Agent attempt | Type, approval state, audit log, tool calls |
| **Interview** | Pre-hire test | Role recipe scenarios, scores, reviewer feedback |
| **Onboarding** | Ramp-up | Role recipe checklist, shadow mode, trial tasks, docs learned |
| **Pulse Event** | Recall unit | Timestamped activity from messages, tasks, approvals, tool use |

---

## AI Employee Object

An AI employee is a **live instance of a role recipe**, customized for a specific workspace.

| Field | Example |
|-------|---------|
| Source recipe | `support-agent-v1.2` |
| Name / role | Maya -- Customer Success Agent |
| Mission | Help onboard and retain customers |
| Manager | Founder / Head of CS / Company Operator |
| Rooms | `#customer-success`, `#onboarding`, `#product-feedback` |
| Tools | CRM, docs, tickets, calendar, analytics |
| Permissions | Can read and draft; needs approval to send or change records |
| Memory scope | Per-agent journal (`memory/<handle>/journal.md`) + granted company docs (`docs/*.txt`) |
| Prompt (resolved) | Base role recipe prompt + company-specific overrides |

### Status Lifecycle

```
Draft -> Interviewing -> Onboarding (shadow) -> Active -> Paused -> Offboarded
```

---

## Security Model

Because AI employees are reachable from outside the company (routed email addresses, shared rooms, ingested documents, vendor replies), Pidgin needs an explicit rule for whose instructions an agent will follow.

The core principle:

> Agents follow instructions only from authenticated peers and superiors inside the workspace. Everything else is data, triage, or a request awaiting human review.

In practice this means every inbound message is resolved to a **principal** by the Pidgin runtime, tagged with a **trust label**, and checked against an **invocation policy** derived from the hierarchy recipe before the agent is allowed to act on it. Content the agent merely *reads* (PDFs, tickets, email bodies) is treated as data and can never originate tool calls on its own.

The full model — principals, trust labels, invocation policy, instructions-vs-data separation, approval gates, attribution, cross-tenant isolation, and agent-to-agent trust — is defined in [SECURITY_SPEC.md](SECURITY_SPEC.md).

---

## Company Pulse

A first-class recall feature that summarizes reality from communication logs: messages, voice notes, calls, meetings, tasks, approvals, agent actions, docs, decisions, and tool activity.

### Supported Queries

- What happened today?
- What did I do today?
- What changed this week?
- What is blocked?
- What did the AI workforce do while I was away?

### MVP Constraints

- Start with **today** and **this week** scopes
- In-app activity only (no external tool ingestion in v0.1)
- Responses include links to source events

---

## User Flows

### Flow 1: Workspace Setup (Day 0)

```
Choose hierarchy recipe (SaaS, agency, etc.)
  -> Company Operator asks: goals, team size, gaps, existing tools
  -> Proposes: org chart, rooms, role recipes to hire, workflows
  -> User confirms -> workspace instantiated from hierarchy recipe
```

**MVP detail:** Hierarchy recipe instantiates rooms, reporting lines, and a recommended hire list. Company Operator is a guided setup wizard, not open-ended chat on day one.

---

### Flow 2: Hire -> Interview -> Onboard

```
Browse role recipes -> select "Support Agent"
  -> Recipe pre-fills: mission, prompts, tools, permissions, rooms
  -> User adjusts overrides (optional) -> assign manager
  -> Interview: scenarios from role recipe (e.g. angry customer, refund request)
  -> Reviewer agent scores + suggests prompt/tool/guardrail changes
  -> User approves -> Onboarding: role recipe checklist, shadow mode in #support
  -> Trial tasks -> Full access (with approval gates)
```

**MVP detail:** The user hires a role, not a blank agent. Interview scenarios and onboarding steps come from the recipe.

---

### Flow 3: Daily Work

```
Human posts in #customer-success or DMs Maya (CS Agent)
  -> Text or voice note
  -> Conversation -> task extracted ("Investigate churn for Acme Corp")
  -> Action buttons: Investigate | Draft | Fix | Review | Execute | Escalate
  -> Agent acts within permissions -> approval if needed -> audit logged
```

**MVP detail:** Start with explicit action buttons and manual task creation. Auto-extraction from conversation is a v0.2 feature.

---

### Flow 4: Company Pulse

```
User asks: "What happened this week?" / "What's blocked?"
  -> Pulse aggregates: messages, tasks, approvals, agent actions, decisions
  -> Returns structured summary with links to source
```

---

## Information Architecture

```
Workspace
+-- Home / Pulse              (what happened today?)
+-- Rooms
|   +-- #general
|   +-- #customer-success
|   +-- DM with Maya (CS Agent)
+-- AI Team                   (roster of hired agents + status)
|   +-- Maya (CS)             -> profile, source recipe, permissions, memory, audit
|   +-- [Hire from recipe]
+-- Recipe Library            (browse hierarchy + role recipes)
|   +-- Hierarchy Recipes
|   +-- Role Recipes
+-- Tasks                     (all work with owners and status)
+-- Interviews                (pending / completed)
+-- Settings
    +-- Workspace
    +-- Integrations
    +-- Permissions
```

---

## MVP Scope

Start as an **AI workforce workspace next to existing tools**, not a full Slack replacement on day one.

### Must Include

| Feature | Notes |
|---------|-------|
| 1 hierarchy recipe | SaaS company |
| 1 role recipe (end-to-end) | Support / CS Agent -- full definition, prompts, interview, onboarding |
| Recipe instantiation | Hire from role recipe; workspace from hierarchy recipe |
| Company operator | Setup wizard + routing (not full chief-of-staff) |
| Hire, interview, reviewer agent, onboarding | Driven by role recipe assets |
| Rooms with humans + agents | Defined by hierarchy recipe: `#general`, `#support`, DM |
| Text + voice-note communication | No calls or meetings in v0.1 |
| Task extraction, action buttons, permissions | Manual task creation + 3 action buttons |
| Company Pulse | Today and this week; in-app only |

### Defer

| Feature | Reason |
|---------|--------|
| Full Slack replacement | Wedge first, replace later |
| Custom roles (build from scratch) | Recipe-first; custom builder in v0.2 |
| Multi-agent role decomposition | Single-agent role recipes first |
| Full browser/computer control | High risk, complex |
| External customer communication | Internal workforce focus first |
| Large open agent marketplace | Curated recipe library first |
| Autonomous high-risk actions | Approval gates required from day one |
| Complex enterprise admin surface | Small team focus first |
| Deep BI/analytics suite | Pulse is sufficient for v0.1 |
| Vector / semantic search | File journals + grep for MVP; see [SCHEMA_SPEC.md](SCHEMA_SPEC.md) |
| OS keychain / secret store integration | User supplies workspace password externally; K8s secrets post-MVP |
| Full DB encryption (SQLCipher) | Plain SQLite per workspace for MVP; see [SCHEMA_SPEC.md §4](SCHEMA_SPEC.md) |
| Recipe marketplace app | Separate app; runtime consumes bundles at hire time |

### MVP Goal

A founder picks the **SaaS hierarchy recipe**, hires a **Support Agent from its role recipe**, passes interview, onboard in shadow mode, communicates by text/voice, assigns a task with approval gates, and asks "what happened today."

### Wedge Role Recipe: Support / CS Agent

Best first role recipe because:

- Clear, realistic interview scenarios
- Measurable outcomes (response quality, escalation correctness)
- Contained permissions (read + draft, approve before send)
- High value for target users (SaaS founders)
- Exercises the full recipe lifecycle: definition -> prompts -> interview -> onboarding -> active work

---

## Success Criteria

| Metric | Target |
|--------|--------|
| Time to first hired agent | < 30 minutes (recipe pre-fills most config) |
| Interview -> onboard -> first real task | < 1 day |
| Pulse utility | User can answer "what did the AI do today?" without reading every message |
| Trust signal | User approves agent for full access after shadow mode |
| Recipe clarity | User can explain what their AI employee does without reading the prompt |

---

## Competitive Framing

| Product | What It Is | Gap We Fill |
|---------|------------|-------------|
| Slack + bots | Chat with bolted-on agents | No recipes, no hire/onboard/audit lifecycle |
| Cursor / Devin | Individual AI workers | Not org-wide; no hierarchy or role packages |
| Relevance AI / agent platforms | Build and deploy agents | Blank canvas; no premade org or role recipes |
| Notion AI / Copilot | Assistive AI in existing tools | AI isn't an "employee" with a recipe-backed role |
| Prompt marketplaces | Sell prompt snippets | Snippets, not full role packages with lifecycle |

**Our lane:** The HR + ops + comms layer for AI labor -- powered by **recipes** that define how companies and roles actually work.

---

## Strategic Moat

The moat is the **operating layer around AI labor**, with **recipes as the core IP**:

- **Hierarchy recipes** -- how AI-native companies are organized
- **Role recipes** -- how human jobs are performed by AI employees (definition + prompts + lifecycle)
- Identity, hiring, interviews, onboarding
- Permissions, memory, task history
- Reviews, audit trail
- Recipe improvement loop (reviewer agent -> better recipes over time)

Chat and agent frameworks are commoditizing. Curated, tested recipes for org structure and job performance are not.

---

## Open Decisions

| # | Decision | Options | Recommendation |
|---|----------|---------|----------------|
| 1 | Comms layer | Custom chat UI vs. embed/bridge Slack | Custom UI for MVP (full control over AI employee UX) |
| 2 | Agent runtime | Own framework vs. orchestrate existing | **Own runtime in Python** — see [TECH_STACK_SPEC.md](TECH_STACK_SPEC.md), [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) |
| 3 | Recipe format | YAML/JSON files vs. DB-backed with UI editor | Files in repo for MVP; UI editor in v0.2 |
| 4 | Recipe versioning | Semantic versioning vs. immutable snapshots | Snapshots on hire; recipe library gets semver |
| 5 | Pulse data source | In-app only vs. ingest Slack/email | In-app only for MVP |
| 6 | Pricing model | Per seat / per agent / per recipe / workspace tier | TBD |
| 7 | Product name | Working title: Pidgin | Pidgin fits (human -> AI communication layer) |

---

## Roadmap Tiers

| Pillar | MVP (v0.1) | v0.2 | Later |
|--------|------------|------|-------|
| Hierarchy recipes | 1 (SaaS) | 3-5 company types | Custom hierarchy builder |
| Role recipes | 1 (Support Agent) | 5-7 roles | Community recipe marketplace |
| Recipe library UI | Browse + hire | Preview scenarios, compare versions | Publish and share recipes |
| Company Operator | Setup wizard + routing | Ongoing chief-of-staff | Proactive suggestions |
| Hire / Interview / Reviewer | Full flow via role recipe | Multi-agent role decomposition | Custom role builder |
| Onboarding | Role recipe checklist + shadow | Doc ingestion, room assignment | Auto-ramp |
| Communication | Text + voice notes | Calls, meetings | Screen-share |
| Rooms | From hierarchy recipe | @mentions, threads | Full Slack parity |
| Tasks & actions | Manual task creation + action buttons | Auto-extraction from chat | Workflow automation |
| Permissions & audit | Read/draft/approve gates | Role-based policies | Enterprise admin |
| Company Pulse | Today / this week, in-app only | Cross-tool ingestion | BI / analytics |
| Agent memory & recall | Per-agent `journal.md` + grep | FTS on file corpus | Semantic / vector search |
| Workspace storage | Plain SQLite + files; external password | SQLCipher; K8s secret injection | Multi-tenant Postgres |

---

## Next Spec Documents

### Product and integration

- [x] [INTEGRATION_WOFKLOW.md](INTEGRATION_WOFKLOW.md) — connector model, virtual agent identities, attribution
- [x] [SECURITY_SPEC.md](SECURITY_SPEC.md) — principals, trust labels, invocation policy, approval gates

### Runtime and platform (done)

- [x] [AGENT_RUNTIME_SPEC.md](AGENT_RUNTIME_SPEC.md) — triggers, actions, turn lifecycle, gate, MVP process model
- [x] [SCHEMA_SPEC.md](SCHEMA_SPEC.md) — 26 tables, file-based memory, workspace storage
- [x] [TECH_STACK_SPEC.md](TECH_STACK_SPEC.md) — Python stack, libraries, explicit MVP omissions

### Still to write

- [ ] `RECIPES_SPEC.md` — hierarchy recipe schema, role recipe schema, example recipes
- [ ] `INTERVIEW_SPEC.md` — scenarios, scoring rubric, reviewer output format
- [ ] `AI_EMPLOYEE_SCHEMA.md` — full object model + API shape
- [ ] `MVP_USER_STORIES.md` — epics and acceptance criteria for v0.1
- [ ] `ARCHITECTURE.md` — how recipes, agents, rooms, and Pulse connect (may fold into existing specs)
- [ ] `SECURITY_PROTOCOLS_SPEC.md` — DKIM/DMARC, OAuth, mTLS, signed A2A, MCP auth, SSO/SCIM
