import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  type Agent,
  type AgentInspect,
  type AgentInspectTimer,
  type AgentInspectTurn,
  type ChangeGatingConfig,
  type LlmInvocation,
} from "../api/client";
import { useApp } from "../context/AppContext";

function statusLabel(status: string): string {
  if (status === "draft") return "Agent Deactivated";
  if (status === "offboarded") return "archived";
  return status;
}

function statusTone(status: string): string {
  if (status === "active") return "#1f9d55";
  if (status === "offboarded") return "#a0a0a0";
  return "#c07800"; // deactivated / other
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className="badge" style={{ background: statusTone(status), color: "#fff" }}>
      {statusLabel(status)}
    </span>
  );
}

function timerSummary(timer: AgentInspectTimer): string {
  const r = timer.recurrence;
  if (r && r.kind === "interval" && r.every_minutes) return `every ${r.every_minutes} min`;
  if (r && r.kind === "daily") return `daily ${r.at_local_time ?? ""}`.trim();
  if (r && r.kind === "weekly") return `weekly ${r.weekday ?? ""} ${r.at_local_time ?? ""}`.trim();
  if (timer.kind === "bootstrap") return "one-off (bootstrap)";
  return "one-off";
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const labels: Record<string, string> = {
    executed: "done",
    staged: "awaiting approval",
    refused: "refused",
    failed: "failed",
  };
  return <span className={`badge outcome-${outcome}`}>{labels[outcome] ?? outcome}</span>;
}

// All displayed times carry their zone (spec §4.6). We show the viewer's local
// zone via toLocaleString; guaranteed wake times are stored as UTC HH:MM.
function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { timeZoneName: "short" });
}

const SOURCE_SHORT: Record<string, string> = {
  inbound_events: "new messages",
  task_state: "task changes",
  approvals: "approvals",
  watched_resources: "watched resources",
  delegated_returns: "delegated returns",
};

// Group the turn list into real turns and runs of consecutive skips of the SAME
// timer — the per-agent view collapses skips per-timer (spec §4.7).
type WakeupGroup =
  | { kind: "turn"; turn: AgentInspectTurn }
  | { kind: "skips"; timerId: string | null; reason: string; turns: AgentInspectTurn[] };

function groupWakeups(turns: AgentInspectTurn[]): WakeupGroup[] {
  const groups: WakeupGroup[] = [];
  for (const turn of turns) {
    if (turn.current_status === "skipped") {
      const last = groups[groups.length - 1];
      if (last && last.kind === "skips" && last.timerId === (turn.timer_id ?? null)) {
        last.turns.push(turn);
      } else {
        groups.push({
          kind: "skips",
          timerId: turn.timer_id ?? null,
          reason: turn.timer_reason ?? "recurring wake-up",
          turns: [turn],
        });
      }
    } else {
      groups.push({ kind: "turn", turn });
    }
  }
  return groups;
}

function SkipStrip({ group }: { group: Extract<WakeupGroup, { kind: "skips" }> }) {
  const [open, setOpen] = useState(false);
  const turns = group.turns;
  const newest = turns[0];
  const oldest = turns[turns.length - 1];
  const label = (group.reason.length > 60 ? `${group.reason.slice(0, 60)}…` : group.reason).trim();
  const range =
    turns.length === 1
      ? fmtTime(newest.started_at)
      : `${fmtTime(oldest.started_at)} – ${fmtTime(newest.started_at)}`;

  return (
    <li style={{ padding: "0.3rem 0", borderTop: "1px solid var(--border,#2a2a2a)" }}>
      <button
        type="button"
        className="secondary"
        onClick={() => setOpen((v) => !v)}
        style={{ width: "100%", textAlign: "left", background: "transparent", border: "none", padding: 0, cursor: "pointer" }}
      >
        <span className="muted">⤳ </span>
        <strong>{turns.length}</strong> skipped
        <span className="muted"> · nothing changed · {label} · {range} </span>
        <span className="muted">{open ? "▾" : "▸"}</span>
      </button>
      {open ? (
        <ul style={{ listStyle: "none", margin: "0.3rem 0 0", padding: "0 0 0 1rem" }}>
          {turns.map((t) => {
            const counts = t.probe_snapshot?.counts ?? {};
            const summary = Object.keys(counts).length
              ? Object.entries(counts).map(([k, v]) => `${v} ${SOURCE_SHORT[k] ?? k}`).join(" · ")
              : "no sources checked";
            return (
              <li key={t.id} className="muted" style={{ fontSize: "0.8rem", padding: "0.15rem 0" }}>
                <span style={{ fontFamily: "monospace" }}>{fmtTime(t.started_at)}</span> — {summary}
                {t.probe_snapshot?.baseline ? (
                  <span> · since {fmtTime(t.probe_snapshot.baseline)}</span>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </li>
  );
}

function RecentWakeups({ turns }: { turns: AgentInspectTurn[] }) {
  const groups = groupWakeups(turns);
  const skipped = turns.filter((t) => t.current_status === "skipped").length;
  return (
    <div className="panel stack">
      <h4 style={{ margin: 0 }}>
        Recent wake-ups{skipped > 0 ? <span className="muted"> · {skipped} skipped</span> : null}
      </h4>
      {groups.length === 0 ? (
        <p className="muted">No wake-ups yet.</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {groups.map((g, i) =>
            g.kind === "skips" ? (
              <SkipStrip key={`skips-${i}`} group={g} />
            ) : (
              <li
                key={g.turn.id}
                className="row"
                style={{ gap: "0.6rem", alignItems: "baseline", padding: "0.3rem 0", borderTop: "1px solid var(--border,#2a2a2a)" }}
              >
                <span className="muted" style={{ fontFamily: "monospace", fontSize: "0.78rem" }}>
                  {fmtTime(g.turn.started_at)}
                </span>
                <span className="badge">{g.turn.current_status}</span>
                <span className="muted">{g.turn.trigger_type ?? "?"}</span>
              </li>
            ),
          )}
        </ul>
      )}
    </div>
  );
}

function ChangeGatingPanel({
  slug,
  handle,
  config,
  onSaved,
}: {
  slug: string;
  handle: string;
  config: ChangeGatingConfig;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [enabled, setEnabled] = useState(config.change_gating_enabled);
  const [times, setTimes] = useState<string[]>(config.guaranteed_wake_times);
  const [sources, setSources] = useState<string[]>(config.change_sources);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      await api.putChangeGating(slug, handle, {
        change_gating_enabled: enabled,
        guaranteed_wake_times: times,
        change_sources: sources,
      });
      setMsg("Saved.");
      onSaved();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  function toggleSource(key: string) {
    setSources((s) => (s.includes(key) ? s.filter((k) => k !== key) : [...s, key]));
  }

  return (
    <div className="panel stack">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{ background: "transparent", border: "none", padding: 0, cursor: "pointer", textAlign: "left" }}
      >
        <h4 style={{ margin: 0 }}>
          Advanced · change-gated wake-ups <span className="muted">{open ? "▾" : "▸"}</span>
        </h4>
      </button>
      {open ? (
        <div className="stack" style={{ gap: "0.75rem" }}>
          <label className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            <span>
              Skip a recurring wake-up when nothing changed
              <span className="muted"> — off means every wake-up runs a full turn</span>
            </span>
          </label>

          <div>
            <div className="muted" style={{ fontSize: "0.85rem", marginBottom: "0.25rem" }}>
              Guaranteed daily wake times (always run, even with no change) · UTC
            </div>
            <div className="row" style={{ flexWrap: "wrap", gap: "0.4rem", alignItems: "center" }}>
              {times.map((t, i) => (
                <span key={i} className="row" style={{ gap: "0.2rem", alignItems: "center" }}>
                  <input
                    type="time"
                    value={t}
                    onChange={(e) =>
                      setTimes((arr) => arr.map((v, j) => (j === i ? e.target.value : v)))
                    }
                  />
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setTimes((arr) => arr.filter((_, j) => j !== i))}
                    aria-label="Remove wake time"
                  >
                    ×
                  </button>
                </span>
              ))}
              <button type="button" className="secondary" onClick={() => setTimes((arr) => [...arr, "12:00"])}>
                + add time
              </button>
            </div>
          </div>

          <div>
            <div className="muted" style={{ fontSize: "0.85rem", marginBottom: "0.25rem" }}>
              Changes that count as a reason to wake
            </div>
            <div className="stack" style={{ gap: "0.2rem" }}>
              {config.all_sources.map((s) => (
                <label key={s.key} className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={sources.includes(s.key)}
                    onChange={() => toggleSource(s.key)}
                  />
                  <span>{s.label}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
            <button type="button" disabled={busy} onClick={() => void save()}>
              {busy ? "Saving…" : "Save"}
            </button>
            {msg ? <span className="muted">{msg}</span> : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function AgentDetail({ slug, handle }: { slug: string; handle: string }) {
  const [data, setData] = useState<AgentInspect | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await api.inspectAgent(slug, handle));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load agent");
    }
  }, [slug, handle]);

  useEffect(() => {
    setData(null);
    void load();
  }, [load]);

  async function toggleActivation(activate: boolean) {
    setBusy(true);
    setError(null);
    try {
      if (activate) await api.activateAgent(slug, handle);
      else await api.deactivateAgent(slug, handle);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  const back = (
    <Link to={`/${slug}/dashboard`} className="muted">
      ← All agents
    </Link>
  );

  if (error) {
    return (
      <div className="stack">
        {back}
        <div className="error">{error}</div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="stack">
        {back}
        <p className="muted">Loading…</p>
      </div>
    );
  }

  const { agent } = data;
  const isActive = agent.current_status === "active";
  const archived = agent.current_status === "offboarded";

  return (
    <div className="stack">
      {back}

      <div className="panel stack">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div className="row" style={{ gap: "0.5rem", alignItems: "baseline" }}>
              <h2 style={{ margin: 0 }}>{agent.display_name}</h2>
              <StatusBadge status={agent.current_status} />
              {data.is_working ? (
                <span className="badge" style={{ background: "#1f6feb", color: "#fff" }}>
                  ● working now
                </span>
              ) : null}
            </div>
            <p className="muted" style={{ margin: "0.25rem 0 0" }}>
              {agent.role_title} · @{agent.handle}
            </p>
            <p className="muted" style={{ margin: "0.25rem 0 0", fontSize: "0.85rem" }}>
              {agent.bootstrapped_at
                ? `Bootstrapped ${new Date(agent.bootstrapped_at).toLocaleString()}`
                : "Never activated — runs only when messaged"}
            </p>
          </div>
          <div className="row" style={{ gap: "0.5rem" }}>
            <Link to={`/${slug}/dashboard/${agent.handle}/console`} className="btn secondary">
              Console
            </Link>
            <Link to={`/${slug}/agents/${agent.handle}/chat`} className="btn secondary">
              Chat
            </Link>
            {!archived ? (
              <button
                type="button"
                disabled={busy}
                className={isActive ? "secondary" : ""}
                onClick={() => void toggleActivation(!isActive)}
              >
                {busy ? "…" : isActive ? "Deactivate" : "Activate"}
              </button>
            ) : null}
            <button type="button" className="secondary" disabled={busy} onClick={() => void load()}>
              Refresh
            </button>
          </div>
        </div>
        <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
          {data.current_turn
            ? `Latest turn: ${data.current_turn.current_status} · ${
                data.current_turn.trigger_type ?? "?"
              } · ${new Date(data.current_turn.started_at).toLocaleString()}`
            : "No turns yet."}
        </p>
      </div>

      {data.open_approvals.length > 0 ? (
        <div className="warning">
          {data.open_approvals.length} action(s) awaiting your approval —{" "}
          <Link to={`/${slug}/approvals`}>review in Approvals</Link>.
        </div>
      ) : null}

      <div className="split-layout">
        <div className="panel stack">
          <h4 style={{ margin: 0 }}>Task list ({data.tasks.length})</h4>
          {data.tasks.length === 0 ? (
            <p className="muted">No open tasks.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {data.tasks.map((task) => (
                <li key={task.id} style={{ padding: "0.35rem 0", borderTop: "1px solid var(--border,#2a2a2a)" }}>
                  <span className="badge" style={{ marginRight: "0.5rem" }}>
                    {task.current_status}
                  </span>
                  {task.title}
                  {task.due_at ? <span className="muted"> · due {task.due_at}</span> : null}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="panel stack">
          <h4 style={{ margin: 0 }}>Timers ({data.timers.length})</h4>
          {data.timers.length === 0 ? (
            <p className="muted">
              No scheduled wake-ups.{isActive ? " (Heartbeat may not be armed yet.)" : ""}
            </p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {data.timers.map((timer) => (
                <li key={timer.id} style={{ padding: "0.35rem 0", borderTop: "1px solid var(--border,#2a2a2a)" }}>
                  <span className="badge" style={{ marginRight: "0.5rem" }}>
                    {timerSummary(timer)}
                  </span>
                  <span className="muted" style={{ fontFamily: "monospace", fontSize: "0.8rem" }}>
                    {new Date(timer.scheduled_at).toLocaleString()}
                  </span>
                  <div className="muted" style={{ fontSize: "0.85rem" }}>
                    {timer.reason.length > 120 ? `${timer.reason.slice(0, 120)}…` : timer.reason}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="panel stack">
        <h4 style={{ margin: 0 }}>Tools ({data.tools.length})</h4>
        <div className="row" style={{ flexWrap: "wrap", gap: "0.4rem" }}>
          {data.tools.map((tool) => (
            <span key={tool.name} className="badge" title={tool.description}>
              {tool.name}
            </span>
          ))}
        </div>
      </div>

      <RecentWakeups turns={data.recent_turns} />

      <ChangeGatingPanel slug={slug} handle={handle} config={data.change_gating} onSaved={() => void load()} />

      <div className="panel stack">
        <h4 style={{ margin: 0 }}>Recent actions</h4>
        {data.recent_actions.length === 0 ? (
          <p className="muted">No actions recorded yet.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {data.recent_actions.map((entry) => (
              <li
                key={entry.id}
                className="row"
                style={{ gap: "0.6rem", alignItems: "baseline", padding: "0.3rem 0", borderTop: "1px solid var(--border,#2a2a2a)" }}
              >
                <span className="muted" style={{ fontFamily: "monospace", fontSize: "0.78rem" }}>
                  {new Date(entry.occurred_at).toLocaleString()}
                </span>
                <span style={{ fontWeight: 600 }}>{entry.action_type}</span>
                <OutcomeBadge outcome={entry.outcome} />
                <Link to={`/${slug}/debug/turns/${entry.turn_id}`} className="muted">
                  turn
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function ConsoleEntry({ invocation }: { invocation: LlmInvocation }) {
  // The "input" for a call is the newest message in the request: the user's
  // message on the first call, or the tool results fed back on later calls.
  const messages = invocation.request_messages;
  const tail = messages.length > 0 ? messages[messages.length - 1] : null;
  const isToolResult = tail?.role === "user" && tail.content.startsWith("Tool results:");
  const inputLabel = isToolResult ? "tool result" : (tail?.role ?? "input");
  const response = invocation.response;
  const actions = response?.actions ?? [];

  return (
    <div className="panel stack" style={{ gap: "0.5rem" }}>
      <div
        className="row muted"
        style={{ gap: "0.6rem", fontSize: "0.78rem", flexWrap: "wrap", alignItems: "baseline" }}
      >
        <span style={{ fontFamily: "monospace" }}>{new Date(invocation.invoked_at).toLocaleString()}</span>
        <span>req-{invocation.id.slice(-6).toLowerCase()}</span>
        <span>#{invocation.sequence_in_turn}</span>
        <span>{invocation.trigger_type ?? "?"}</span>
        <span>
          {invocation.input_tokens.toLocaleString()}→{invocation.output_tokens.toLocaleString()} tok
        </span>
        {invocation.latency_ms != null ? <span>{invocation.latency_ms} ms</span> : null}
        {invocation.turn_status ? <span>{invocation.turn_status}</span> : null}
      </div>

      <div>
        <div className="muted" style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
          ▸ input · {inputLabel}
        </div>
        <pre className="llm-message-body" style={{ margin: "0.25rem 0 0" }}>
          {tail ? tail.content : "(no input)"}
        </pre>
      </div>

      <div>
        <div className="muted" style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
          ◂ output · stop: {response?.stop_reason ?? "—"}
        </div>
        {invocation.error_text ? <div className="error">{invocation.error_text}</div> : null}
        {response?.assistant_text ? (
          <pre className="llm-message-body" style={{ margin: "0.25rem 0 0" }}>
            {response.assistant_text}
          </pre>
        ) : null}
        {actions.map((action, i) => (
          <div key={i} style={{ marginTop: "0.35rem" }}>
            <span className="badge">{action.action_type}</span>
            <pre className="llm-message-body" style={{ margin: "0.25rem 0 0" }}>
              {JSON.stringify(action.params, null, 2)}
            </pre>
          </div>
        ))}
        {!response?.assistant_text && actions.length === 0 && !invocation.error_text ? (
          <p className="muted" style={{ margin: "0.25rem 0 0" }}>No text or tool calls.</p>
        ) : null}
      </div>
    </div>
  );
}

function AgentConsole({ slug, handle }: { slug: string; handle: string }) {
  const [agentId, setAgentId] = useState<string | null>(null);
  const [rows, setRows] = useState<LlmInvocation[]>([]);
  const [live, setLive] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const rowsRef = useRef(rows);
  rowsRef.current = rows;

  // Resolve the handle → agent id once (invocations filter by id).
  useEffect(() => {
    let cancelled = false;
    api
      .inspectAgent(slug, handle)
      .then((d) => {
        if (!cancelled) setAgentId(d.agent.id);
      })
      .catch((err: Error) => setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [slug, handle]);

  const poll = useCallback(async () => {
    if (!agentId) return;
    try {
      const newest = rowsRef.current[0]?.id;
      const incoming = await api.listLlmInvocations(slug, {
        agentId,
        limit: 100,
        after: newest,
      });
      setError(null);
      if (incoming.length === 0) return;
      setRows((current) => {
        const seen = new Set(current.map((r) => r.id));
        const fresh = incoming.filter((r) => !seen.has(r.id));
        return fresh.length ? [...fresh, ...current].slice(0, 200) : current;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load console");
    }
  }, [slug, agentId]);

  useEffect(() => {
    void poll();
  }, [poll]);

  useEffect(() => {
    if (!live || !agentId) return;
    const timer = window.setInterval(() => void poll(), 2000);
    return () => window.clearInterval(timer);
  }, [live, agentId, poll]);

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <Link to={`/${slug}/dashboard/${handle}`} className="muted">
          ← Back to agent
        </Link>
        <button
          type="button"
          className={live ? "" : "secondary"}
          onClick={() => setLive((v) => !v)}
        >
          {live ? "● Live" : "Paused"}
        </button>
      </div>
      <h2 style={{ margin: 0 }}>Console · @{handle}</h2>
      <p className="muted" style={{ margin: 0 }}>
        Every request the agent sends to the model (input) and what it sends back (output),
        newest first. Updates live.
      </p>
      {error ? <div className="error">{error}</div> : null}
      {rows.length === 0 ? (
        <p className="muted">No model calls recorded for this agent yet.</p>
      ) : (
        <div className="stack">
          {rows.map((row) => (
            <ConsoleEntry key={row.id} invocation={row} />
          ))}
        </div>
      )}
    </div>
  );
}

function AgentList({ slug }: { slug: string }) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listAgents(slug)
      .then(setAgents)
      .catch((err: Error) => setError(err.message));
  }, [slug]);

  return (
    <div className="stack">
      <h2 style={{ margin: 0 }}>Agent Dashboard</h2>
      <p className="muted" style={{ margin: 0 }}>
        Pick an agent to inspect its status, current activity, task list, timers, tools, and actions.
      </p>
      {error ? <div className="error">{error}</div> : null}

      {agents.length === 0 ? (
        <p className="muted">No agents yet.</p>
      ) : (
        <div className="stack">
          {agents.map((agent) => (
            <Link
              key={agent.id}
              to={`/${slug}/dashboard/${agent.handle}`}
              className="panel row"
              style={{
                justifyContent: "space-between",
                alignItems: "center",
                textDecoration: "none",
                cursor: "pointer",
              }}
            >
              <div>
                <div style={{ fontWeight: 600 }}>{agent.display_name}</div>
                <div className="muted" style={{ fontSize: "0.85rem" }}>
                  {agent.role_title} · @{agent.handle}
                </div>
              </div>
              <div className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
                <StatusBadge status={agent.current_status} />
                <span className="muted">›</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export function AgentDashboardPage({ view }: { view?: "console" } = {}) {
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const { handle = "" } = useParams();

  if (!slug) return null;
  if (handle && view === "console") return <AgentConsole slug={slug} handle={handle} />;
  return handle ? <AgentDetail slug={slug} handle={handle} /> : <AgentList slug={slug} />;
}
