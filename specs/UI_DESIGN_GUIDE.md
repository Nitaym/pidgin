# Pidgin UI Design Guide

Visual and interaction standards for the Pidgin admin UI (`src/frontend/`). The aesthetic is **Linear-inspired**: dark-first, minimal chrome, keyboard-friendly, and content-focused.

**Audience:** Fullstack dev agents and anyone touching React UI. Read this before adding pages, components, or CSS.

**Related:** [HIRE_UX.md](HIRE_UX.md) (product vocabulary), [MVP_USER_STORIES.md](MVP_USER_STORIES.md) (acceptance criteria).

---

## 1. Design principles

| Principle | What it means in Pidgin |
|-----------|-------------------------|
| **Dark mode first** | True near-black backgrounds; no light theme in MVP |
| **Content over chrome** | Borders and panels are subtle; hierarchy comes from typography and spacing |
| **Precision** | 1px borders, consistent 4–8px radii, aligned baselines |
| **Keyboard-aware** | Primary actions show shortcut hints where applicable (e.g. hire, send) |
| **Functional color** | Color signals status and primary actions — not decoration |
| **Slack-like IA, Linear look** | Navigation and rooms follow workforce/chat semantics; visuals follow Linear |

We borrow Linear's **visual language**, not its issue-tracker information architecture. Pidgin screens map to workforce concepts (team, hire, chat, templates).

---

## 2. Color tokens

All colors live as CSS custom properties in `src/frontend/src/index.css`. **Do not hardcode hex values in components** — use variables.

| Token | Value | Usage |
|-------|-------|-------|
| `--bg-base` | `#0a0a0a` | App shell, main content background |
| `--bg-sidebar` | `#0f0f0f` | Left navigation |
| `--bg-elevated` | `#161616` | Cards, panels, modals |
| `--bg-hover` | `#1c1c1c` | Nav item hover, row hover |
| `--bg-active` | `#222222` | Selected nav item, active tab pill |
| `--border` | `#1f1f1f` | Dividers, panel outlines |
| `--border-strong` | `#2a2a2a` | Input focus, modal edge |
| `--text-primary` | `#ededed` | Headings, body |
| `--text-secondary` | `#8a8a8a` | Descriptions, timestamps, section labels |
| `--text-tertiary` | `#5c5c5c` | Placeholders, disabled |
| `--accent` | `#5e6ad2` | Primary buttons, links, brand accent |
| `--accent-hover` | `#6872d9` | Primary button hover |
| `--accent-muted` | `rgba(94, 106, 210, 0.15)` | Subtle accent backgrounds |
| `--danger` | `#e5484d` | Errors |
| `--danger-bg` | `rgba(229, 72, 77, 0.12)` | Error banners |
| `--success` | `#46a758` | Success states |
| `--success-bg` | `rgba(70, 167, 88, 0.12)` | Success banners |
| `--human-msg` | `#1a2332` | Human chat bubble |
| `--agent-msg` | `#141a14` | Agent chat bubble |

**Brand:** Pidgin logo uses navy + teal/purple/green accents. UI accent is indigo (`--accent`) to match Linear's primary action color; logo colors appear only in the logo asset and optional status dots.

---

## 3. Typography

- **Font:** [Inter](https://rsms.me/inter/) via Google Fonts (loaded in `index.html`)
- **Fallback:** `system-ui, -apple-system, sans-serif`
- **Base size:** 13px (`0.8125rem`) — Linear uses compact type
- **Line height:** 1.5 for body; 1.25 for headings

| Element | Size | Weight | Color |
|---------|------|--------|-------|
| Page title (h2 in main) | 15px | 600 | `--text-primary` |
| Section title (h3) | 14px | 600 | `--text-primary` |
| Body | 13px | 400 | `--text-primary` |
| Muted / meta | 12px | 400 | `--text-secondary` |
| Nav item | 14px | 450 | `--text-secondary` (active: `--text-primary`) |
| Section label (sidebar) | 12px | 500 | `--text-tertiary`, uppercase, letter-spacing 0.04em |
| Eyebrow / step label | 11px | 500 | `--text-secondary`, uppercase |

**Sidebar fonts use `px`, not `rem`** — the app root is 13px, so `rem` inside the sidebar compounds and renders smaller than intended. Set sizes in px on `.sidebar` and its children.

---

## 4. Layout

```
┌─────────────────────────────────────────────────────────┐
│ Sidebar (240px)  │  Main content (flex 1)               │
│                  │  ┌─ Page header (title + actions) ─┐ │
│  Logo + workspace│  │                                 │ │
│  ─────────────── │  │  Content / empty state            │ │
│  Nav sections    │  │                                 │ │
│                  │  └─────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

| Region | Width / padding | Notes |
|--------|-----------------|-------|
| Sidebar | 240px fixed | `--bg-sidebar`; 1px right border `--border` |
| Main | `1fr` | `--bg-base`; padding `24px 32px` |
| Auth screens | Centered card, max 440px | Full-viewport `--bg-base`; elevated card |

**Responsive (<768px):** Sidebar stacks above main; split layouts (hire + HR assist) become single column.

**Split layout (hire wizard, agent profile):** Form left (~64%), HR assist panel right (~36%), sticky on desktop.

---

## 5. Sidebar navigation

Structure (see `Layout.tsx`):

1. **Header** — logo + workspace name + optional user email
2. **Primary** — Team (home)
3. **Workforce** — Hire a role, Your templates
4. **System** — Diagnostics

**Active state:** `--bg-active` rounded rectangle (6px radius); optional 2px left accent bar in `--accent` (Linear-style indicator).

**Hover:** `--bg-hover`; no underline on nav links.

Nav links use React Router `NavLink` with class `active` — styled in CSS, not inline.

---

## 6. Components

### 6.1 Buttons

| Class | Appearance | When |
|-------|------------|------|
| default / `.btn` | Filled `--accent`, white text, 6px radius | Primary CTA |
| `.secondary` | Transparent + `--border` border, `--text-primary` | Cancel, secondary actions |
| `.ghost` | No border, `--text-secondary`; hover `--bg-hover` | Tertiary / toolbar |

Padding: `6px 12px` (compact). Font weight 500. No drop shadows on buttons.

**Shortcut badge:** Optional `<kbd>C</kbd>` inside primary buttons for create actions.

### 6.2 Panels / cards

- Class: `.panel`
- Background: `--bg-elevated`
- Border: 1px `--border`
- Radius: 8px
- Padding: 16px–20px
- **No heavy shadows** on panels; modals only use soft shadow

### 6.3 Page header

- Class: `.page-header`
- Flex row: title left, actions right
- Bottom border 1px `--border`, margin-bottom 20px
- Title uses page name; breadcrumb optional (`Workspace › Team`)

### 6.4 Empty states

Linear-style centered empty states for lists with no items:

- Class: `.empty-state`
- Optional wireframe-style icon (simple CSS or inline SVG, monochrome `--text-tertiary`)
- Bold title + muted description
- Primary + secondary button row

Example: Team page with no agents → "No agents yet" + **Hire a role** button.

### 6.5 Forms

- Class: `.field` — label above input
- Inputs: `--bg-base` background, 1px `--border`, 6px radius, no inner shadow
- Focus: `--border-strong` + 1px `--accent` outline (or box-shadow ring)
- Placeholder: `--text-tertiary`
- **Modal / wizard inputs:** borderless title field (large 18px) inside elevated surface — see hire wizard step 2+

### 6.6 Tabs / view switcher

- Class: `.tabs` / `.tab`
- Pill shape, `--bg-hover` inactive, `--bg-active` active
- Used for wizard steps, future list filters

### 6.7 Alerts

| Class | Use |
|-------|-----|
| `.error` | API failures, validation — `--danger` text on `--danger-bg` |
| `.success` | Confirmations — `--success` on `--success-bg` |

### 6.8 Chat messages

- `.message-list` — scrollable column
- `.message.human` — right-aligned, `--human-msg`
- `.message.agent` — left-aligned, `--agent-msg`
- `.meta` — sender name, `--text-secondary`, 11px

### 6.9 Tables

- Minimal: bottom border only on rows
- Header: `--text-secondary`, 12px, font-weight 500
- Row hover: `--bg-hover`

### 6.10 Modals (future)

Centered, `--bg-elevated`, 10px radius, large soft shadow:

```css
box-shadow: 0 16px 70px rgba(0, 0, 0, 0.5);
```

Header: breadcrumb-style muted path; borderless title + description fields.

---

## 7. Spacing scale

Use rem multiples of 4px:

| Token | Value |
|-------|-------|
| `--space-1` | 4px |
| `--space-2` | 8px |
| `--space-3` | 12px |
| `--space-4` | 16px |
| `--space-5` | 20px |
| `--space-6` | 24px |
| `--space-8` | 32px |

Stack utility: `.stack` = `flex-direction: column; gap: var(--space-4)`.

---

## 8. Icons

MVP: Unicode or minimal inline SVG — no icon library required yet.

When adding icons:

- 16×16 or 20×20 viewBox
- 1.5px stroke, round caps
- Color: `--text-secondary` (inactive) or `--text-primary` (active)
- Prefer Lucide-style line icons if introducing a package later

---

## 9. Motion

- Transitions: `150ms ease` for background, border, color
- No page transitions in MVP
- Respect `prefers-reduced-motion: reduce` — disable transitions

---

## 10. Do's and don'ts for agents

### Do

- Extend `index.css` tokens and utility classes before adding one-off styles
- Keep inline `style={{}}` to a minimum (layout exceptions only)
- Match empty states and page headers across new pages
- Use product vocabulary from [HIRE_UX.md](HIRE_UX.md) — never "recipe" in UI
- Verify UI manually in browser against US-* stories

### Don't

- Introduce a light theme or toggle without explicit product approval
- Add heavy gradients, drop shadows on every panel, or bright saturated backgrounds
- Use default browser form styling (always use `.field` inputs)
- Add Tailwind or a component library without updating this guide and TECH_STACK_SPEC
- Copy Linear's issue-specific UI (priority pills, cycles, labels) unless Pidgin gains equivalent features

---

## 11. File map

| File | Responsibility |
|------|----------------|
| `src/frontend/src/index.css` | All design tokens + component classes |
| `src/frontend/index.html` | Inter font link |
| `src/frontend/public/logo.png` | Static copy of wordmark (optional) |
| `src/frontend/src/assets/logo-icon.svg` | Square sidebar icon (bundled by Vite) |
| `src/frontend/src/components/PidginLogo.tsx` | Sidebar logo component |
| `src/frontend/src/components/Layout.tsx` | App shell + sidebar |
| `specs/UI_DESIGN_GUIDE.md` | This document |

---

## 12. Implementation checklist (new page)

1. Wrap content in existing `Layout` route
2. Add `.page-header` if the page has a title + actions
3. Use `.panel` + `.stack` for sections
4. Empty list → `.empty-state` with primary CTA
5. Forms → `.field` labels + inputs; errors → `.error`
6. Manual browser pass + screenshot for the matching US-* story

---

## 13. Reference

Visual reference: Linear app (dark mode) — sidebar density, empty states, modal create flow, and indigo primary actions. Pidgin screenshots for regression should be compared against the patterns above, not pixel-perfect Linear parity.
