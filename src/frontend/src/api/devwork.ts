// Developer Worker API (specs/DEVELOPER_WORKER_SPEC.html §4).

async function call<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers ?? {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export type QueueItem = {
  id: string;
  key: string;
  title: string;
  url: string;
  class: "assigned" | "agent_ready";
  priority: number;
  reason: string;
  follow_up: boolean;
  last_status: string | null;
};

export type DevWorker = {
  ai_employee_id: string;
  enabled: number;
  linear_installation_id: string | null;
  team_id: string | null;
  team_key: string | null;
  viewer_id: string | null;
  viewer_name: string | null;
  owner_linear_id: string | null;
  owner_linear_name: string | null;
  repo_path: string | null;
  base_branch: string;
  worktree_root: string | null;
  setup_command: string | null;
  branch_pattern: string;
  max_concurrent: number;
  time_limit_min: number;
  idle_limit_min: number;
  max_turns: number;
  poll_seconds: number;
  model: string | null;
  permission_mode: "allowlist" | "bypass";
  allowed_tools: string;
  rules: {
    assigned: boolean;
    agent_ready: boolean;
    agent_ready_label: string;
    skip_labels: string[];
    failed_label: string;
  };
  status_map: Record<"todo" | "in_progress" | "needs_owner" | "done" | "triage", string>;
  queue: QueueItem[];
  last_poll_at: string | null;
  last_poll_ok_at: string | null;
  last_poll_error: string | null;
};

export type CodeRun = {
  id: string;
  ai_employee_id: string;
  ticket_id: string;
  ticket_key: string;
  ticket_title: string | null;
  ticket_url: string | null;
  trigger_class: string;
  attempt: number;
  status: string;
  outcome: string | null;
  outcome_summary: string | null;
  branch: string | null;
  worktree_path: string | null;
  base_sha: string | null;
  head_sha: string | null;
  session_id: string | null;
  last_output_at: string | null;
  log_dir: string | null;
  exit_code: number | null;
  failure_reason: string | null;
  stop_requested: number;
  stopped_by: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cache_read_tokens: number | null;
  cache_write_tokens: number | null;
  cost_usd: number | null;
  num_turns: number | null;
  comments_posted: number;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  ticket_touched_at: string | null;
  ticket_seen_at: string | null;
  first_output_at: string | null;
};

export type Polling = {
  every: number;
  base: number;
  running_check_every: number;
  slowed?: string | null;
  poll_ms?: number;
  poll_complexity?: number | null;
  requests_remaining?: number | null;
  requests_limit?: number | null;
  requests_reset?: number | null;
  complexity_remaining?: number | null;
  complexity_limit?: number | null;
};

export type DevSummary = {
  agent: { id: string; handle: string; display_name: string; role_title: string; current_status: string };
  worker: DevWorker;
  linear_installations: { id: string; display_name: string; status: string }[];
  active: CodeRun[];
  recent: CodeRun[];
  stats: {
    running: number;
    active: number;
    queued: number;
    handed_off: number;
    failed_24h: number;
    cost_24h: number;
    tokens_24h: number;
  };
  runner_alive: boolean;
  polling: Polling;
};

export type LinearTeams = {
  viewer: { id: string; name: string; email: string };
  organization: { name: string; urlKey: string };
  teams: { id: string; key: string; name: string }[];
};

export type LinearTeamMeta = {
  id: string;
  key: string;
  name: string;
  states: { id: string; name: string; type: string }[];
  members: { id: string; name: string; displayName: string; email: string; active: boolean }[];
};

export type RepoCheck = {
  ok: boolean;
  checks: { level: "ok" | "warn" | "error"; text: string }[];
  toplevel?: string;
};

export type RunEvent = { id: string; kind: string; message: string; data_json: string | null; occurred_at: string };
export type LogLine = { kind: "text" | "tool" | "error" | "result" | "system"; text: string };

export type TranscriptEntry =
  | { k: "init"; text: string }
  | { k: "say"; text: string }
  | { k: "todos"; items: { text: string; status: "pending" | "in_progress" | "completed" }[] }
  | { k: "tool"; name: string; arg: string; status: "pending" | "ok" | "error"; out: string[]; more: number }
  | { k: "end"; ok: boolean; text: string };

export type Transcript = { prompt: string; entries: TranscriptEntry[]; total: number };

export type RunDetail = {
  run: CodeRun;
  agent: { handle: string; display_name: string } | null;
  events: RunEvent[];
  log: LogLine[];
  transcript: Transcript;
  stderr: string;
};

export type Terminals = { terminals: { run: CodeRun; transcript: Transcript }[] };

const base = (slug: string) => `/${slug}/api/dev`;

export const devApi = {
  summary: (slug: string, handle: string) => call<DevSummary>(`${base(slug)}/${handle}`),
  saveConfig: (slug: string, handle: string, body: Partial<DevWorker> & { enabled?: boolean | number }) =>
    call<DevWorker>(`${base(slug)}/${handle}/config`, { method: "PUT", body: JSON.stringify(body) }),
  pollNow: (slug: string, handle: string) =>
    call<{ status: string }>(`${base(slug)}/${handle}/poll-now`, { method: "POST" }),
  teams: (slug: string, installationId: string) =>
    call<LinearTeams>(`${base(slug)}/linear/${installationId}/teams`),
  team: (slug: string, installationId: string, teamId: string) =>
    call<LinearTeamMeta>(`${base(slug)}/linear/${installationId}/teams/${teamId}`),
  repoCheck: (slug: string, path: string, baseBranch: string) =>
    call<RepoCheck>(`${base(slug)}/repo-check`, {
      method: "POST",
      body: JSON.stringify({ path, base_branch: baseBranch }),
    }),
  run: (slug: string, runId: string) => call<RunDetail>(`${base(slug)}/runs/${runId}`),
  terminals: (slug: string, handle: string) => call<Terminals>(`${base(slug)}/${handle}/terminals`),
  stop: (slug: string, runId: string, reason?: string) =>
    call<{ status: string }>(`${base(slug)}/runs/${runId}/stop`, {
      method: "POST",
      body: JSON.stringify({ reason: reason ?? null }),
    }),
  retry: (slug: string, runId: string) =>
    call<{ status: string }>(`${base(slug)}/runs/${runId}/retry`, { method: "POST" }),
};

export const RUN_STATUS_LABEL: Record<string, string> = {
  queued: "Queued",
  claiming: "Claiming",
  preparing: "Preparing",
  running: "Running",
  done: "Done",
  handed_off: "Needs owner",
  ended_open: "Needs owner",
  failed: "Failed",
  timed_out: "Failed · limit",
  cancelled: "Stopped",
  dropped: "Dropped",
};

export function runTone(status: string): "ok" | "warn" | "bad" | "acc" | "" {
  if (status === "done") return "ok";
  if (status === "handed_off" || status === "ended_open") return "warn";
  if (status === "failed" || status === "timed_out") return "bad";
  if (["queued", "claiming", "preparing", "running"].includes(status)) return "acc";
  return "";
}

export function duration(from: string | null, to: string | null): string {
  if (!from) return "";
  const ms = (to ? new Date(to).getTime() : Date.now()) - new Date(from).getTime();
  const min = Math.max(0, Math.round(ms / 60000));
  if (min < 60) return `${min} m`;
  return `${Math.floor(min / 60)} h ${min % 60} m`;
}

export function ago(iso: string | null): string {
  if (!iso) return "never";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

function secs(from: string | null, to: string | null): number | null {
  if (!from || !to) return null;
  return (new Date(to).getTime() - new Date(from).getTime()) / 1000;
}

function fmtSecs(s: number): string {
  if (s < 60) return `${Math.max(0, s).toFixed(s < 10 ? 1 : 0)} s`;
  return `${Math.floor(s / 60)} m ${Math.round(s % 60)} s`;
}

/** How fast a run started: from the ticket's last change in Linear (its assignment,
 * usually) to Claude's first output, with the steps in a tooltip. */
export function startLatency(run: CodeRun): { text: string; detail: string } | null {
  const total = secs(run.ticket_touched_at, run.first_output_at);
  if (total === null) return null;
  const seen = secs(run.ticket_touched_at, run.ticket_seen_at);
  const started = secs(run.ticket_seen_at, run.started_at);
  const first = secs(run.started_at, run.first_output_at);
  const parts = [
    seen !== null ? `seen ${fmtSecs(seen)} after the ticket changed` : null,
    started !== null ? `Claude Code started ${fmtSecs(started)} later` : null,
    first !== null ? `first output ${fmtSecs(first)} after that` : null,
  ].filter(Boolean);
  return { text: `started in ${fmtSecs(total)}`, detail: parts.join("; ") };
}
