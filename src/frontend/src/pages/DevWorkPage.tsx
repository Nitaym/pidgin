import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ClaudeTerminal } from "../components/ClaudeTerminal";
import {
  ago,
  devApi,
  duration,
  RUN_STATUS_LABEL,
  runTone,
  type CodeRun,
  type DevSummary,
  type DevWorker,
  type LinearTeamMeta,
  type Terminals,
  type LinearTeams,
  type RepoCheck,
} from "../api/devwork";
import { useApp } from "../context/AppContext";
import "../styles/devwork.css";

// Developer Worker · Work tab (specs/DEVELOPER_WORKER_SPEC.html §4.6).

function TicketCell({ run }: { run: { ticket_key: string; ticket_title: string | null; ticket_url: string | null } }) {
  return (
    <>
      <span className="dw-key">{run.ticket_key}</span>
      {run.ticket_url ? (
        <a href={run.ticket_url} target="_blank" rel="noreferrer">
          {run.ticket_title}
        </a>
      ) : (
        run.ticket_title
      )}
    </>
  );
}

function cost(run: CodeRun): string {
  return run.cost_usd != null ? `$${run.cost_usd.toFixed(2)}` : "";
}

type Form = Partial<DevWorker>;

function SetupPanel({
  slug,
  handle,
  summary,
  onSaved,
}: {
  slug: string;
  handle: string;
  summary: DevSummary;
  onSaved: () => void;
}) {
  const w = summary.worker;
  const [form, setForm] = useState<Form>({});
  const [teams, setTeams] = useState<LinearTeams | null>(null);
  const [team, setTeam] = useState<LinearTeamMeta | null>(null);
  const [repo, setRepo] = useState<RepoCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const v = <K extends keyof DevWorker>(key: K): DevWorker[K] =>
    (form[key] !== undefined ? form[key] : w[key]) as DevWorker[K];
  const set = (patch: Form) => {
    setSaved(false);
    setForm((f) => ({ ...f, ...patch }));
  };

  const installationId = v("linear_installation_id");
  const teamId = v("team_id");

  useEffect(() => {
    if (!installationId) return;
    setTeams(null);
    devApi
      .teams(slug, installationId)
      .then(setTeams)
      .catch((e: Error) => setError(e.message));
  }, [slug, installationId]);

  useEffect(() => {
    if (!installationId || !teamId) return;
    devApi
      .team(slug, installationId, teamId)
      .then(setTeam)
      .catch((e: Error) => setError(e.message));
  }, [slug, installationId, teamId]);

  const checkRepo = async () => {
    const path = v("repo_path");
    if (!path) return;
    try {
      setRepo(await devApi.repoCheck(slug, path, v("base_branch") || "main"));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  useEffect(() => {
    if (w.repo_path) void checkRepo();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await devApi.saveConfig(slug, handle, form);
      setForm({});
      setSaved(true);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const states = team?.states.map((s) => s.name) ?? [];
  const statusMap = { ...w.status_map, ...(form.status_map ?? {}) };
  const rules = { ...w.rules, ...(form.rules ?? {}) };
  const missingStatuses = team
    ? (Object.entries(statusMap) as [string, string][]).filter(
        ([, name]) => !states.some((s) => s.toLowerCase() === name.toLowerCase()),
      )
    : [];

  if (summary.linear_installations.length === 0) {
    return (
      <div className="panel stack">
        <h3 style={{ margin: 0 }}>Set up</h3>
        <p className="muted" style={{ margin: 0 }}>
          First connect Linear with the API key of the developer's <strong>own Linear member</strong> (not yours), so
          everything it writes shows as the developer.
        </p>
        <div>
          <Link to={`/${slug}/integrations/linear`} className="btn">
            Connect Linear
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="panel stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Workplace and rules</h3>
        <div className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
          {saved ? <span className="muted">Saved</span> : null}
          <button type="button" disabled={saving || Object.keys(form).length === 0} onClick={() => void save()}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
      {error ? <div className="error">{error}</div> : null}

      <div className="dw-grid2">
        <div className="field">
          <label>Linear connection</label>
          <select
            value={installationId ?? ""}
            onChange={(e) => set({ linear_installation_id: e.target.value, team_id: null, owner_linear_id: null })}
          >
            <option value="">Choose…</option>
            {summary.linear_installations.map((i) => (
              <option key={i.id} value={i.id}>
                {i.display_name} ({i.status})
              </option>
            ))}
          </select>
          {teams ? (
            <span className="field-hint">
              Acts as <strong>{teams.viewer.name}</strong> ({teams.viewer.email}) in {teams.organization.urlKey}
            </span>
          ) : null}
        </div>
        <div className="field">
          <label>Team</label>
          <select
            value={teamId ?? ""}
            onChange={(e) => {
              const t = teams?.teams.find((x) => x.id === e.target.value);
              set({ team_id: e.target.value, team_key: t?.key ?? null, owner_linear_id: null });
            }}
          >
            <option value="">Choose…</option>
            {teams?.teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.key})
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Owner in Linear · gets hand-offs</label>
          <select
            value={v("owner_linear_id") ?? ""}
            onChange={(e) => {
              const m = team?.members.find((x) => x.id === e.target.value);
              set({ owner_linear_id: e.target.value, owner_linear_name: m?.name ?? null });
            }}
          >
            <option value="">Choose…</option>
            {team?.members
              .filter((m) => m.active && m.id !== teams?.viewer.id)
              .map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} ({m.email})
                </option>
              ))}
          </select>
        </div>
        <div className="field">
          <label>Runs at once</label>
          <input
            type="number"
            min={1}
            max={8}
            value={v("max_concurrent")}
            onChange={(e) => set({ max_concurrent: Number(e.target.value) })}
          />
        </div>
      </div>

      <div className="field">
        <label>Repo (local folder)</label>
        <div className="field-inline">
          <input
            value={v("repo_path") ?? ""}
            placeholder="H:\path\to\repo"
            onChange={(e) => set({ repo_path: e.target.value })}
          />
          <button type="button" className="secondary" onClick={() => void checkRepo()}>
            Check
          </button>
        </div>
        {repo
          ? repo.checks.map((c, i) => (
              <div key={i} className="dw-check">
                <span className={c.level}>{c.level === "ok" ? "✓" : c.level === "warn" ? "!" : "✕"}</span> {c.text}
              </div>
            ))
          : null}
      </div>
      <div className="dw-grid4">
        <div className="field">
          <label>Base branch</label>
          <input value={v("base_branch")} onChange={(e) => set({ base_branch: e.target.value })} />
        </div>
        <div className="field">
          <label>Branch name</label>
          <input value={v("branch_pattern")} onChange={(e) => set({ branch_pattern: e.target.value })} />
        </div>
        <div className="field" style={{ gridColumn: "span 2" }}>
          <label>Worktree folder (keep it outside Dropbox)</label>
          <input value={v("worktree_root") ?? ""} onChange={(e) => set({ worktree_root: e.target.value })} />
        </div>
      </div>
      <div className="field">
        <label>Setup command (runs once in each new worktree)</label>
        <input
          value={v("setup_command") ?? ""}
          placeholder="npm ci"
          onChange={(e) => set({ setup_command: e.target.value })}
        />
      </div>

      <h4 style={{ margin: "8px 0 0" }}>Starts work when</h4>
      <div>
        <label className="dw-toggle-row">
          <input
            type="checkbox"
            checked={rules.assigned}
            onChange={(e) => set({ rules: { ...rules, assigned: e.target.checked } })}
          />
          <span>
            A ticket is <strong>assigned to {w.viewer_name ?? "the developer"}</strong> and in{" "}
            <strong>{statusMap.todo}</strong>
            <div className="muted">Assigned work always goes first.</div>
          </span>
        </label>
        <label className="dw-toggle-row">
          <input
            type="checkbox"
            checked={rules.agent_ready}
            onChange={(e) => set({ rules: { ...rules, agent_ready: e.target.checked } })}
          />
          <span>
            An <strong>unassigned</strong> {statusMap.todo} ticket has the <code>{rules.agent_ready_label}</code> label
            <div className="muted">Only when nothing assigned is waiting. It assigns the ticket to itself when it starts.</div>
          </span>
        </label>
        <p className="muted" style={{ margin: "6px 0 0" }}>
          Moving a ticket to {statusMap.todo} on its own does nothing. Skips tickets labelled{" "}
          {rules.skip_labels.map((l) => (
            <code key={l} style={{ marginRight: 4 }}>
              {l}
            </code>
          ))}
          and blocked ones. Mentions and comments don't start work yet: to continue a handed-off ticket, assign it back
          in {statusMap.todo}.
        </p>
      </div>

      <h4 style={{ margin: "8px 0 0" }}>Limits</h4>
      <div className="dw-grid4">
        <div className="field">
          <label>Time limit (min)</label>
          <input type="number" value={v("time_limit_min")} onChange={(e) => set({ time_limit_min: Number(e.target.value) })} />
        </div>
        <div className="field">
          <label>Silent limit (min)</label>
          <input type="number" value={v("idle_limit_min")} onChange={(e) => set({ idle_limit_min: Number(e.target.value) })} />
        </div>
        <div className="field">
          <label>Max turns</label>
          <input type="number" value={v("max_turns")} onChange={(e) => set({ max_turns: Number(e.target.value) })} />
        </div>
        <div className="field">
          <label>Poll Linear every (s)</label>
          <input type="number" min={60} value={v("poll_seconds")} onChange={(e) => set({ poll_seconds: Number(e.target.value) })} />
        </div>
      </div>

      <h4 style={{ margin: "8px 0 0" }}>Statuses</h4>
      <div className="dw-grid4">
        {(["todo", "in_progress", "needs_owner", "done", "triage"] as const).map((key) => (
          <div className="field" key={key}>
            <label>
              {{ todo: "Picks up from", in_progress: "Claims as", needs_owner: "Hands off as", done: "Finishes as", triage: "Files new work in" }[key]}
            </label>
            {states.length ? (
              <select
                value={statusMap[key]}
                onChange={(e) => set({ status_map: { ...statusMap, [key]: e.target.value } })}
              >
                {!states.includes(statusMap[key]) ? <option value={statusMap[key]}>{statusMap[key]} (missing)</option> : null}
                {states.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            ) : (
              <input value={statusMap[key]} onChange={(e) => set({ status_map: { ...statusMap, [key]: e.target.value } })} />
            )}
          </div>
        ))}
      </div>
      {missingStatuses.length ? (
        <div className="dw-banner warn">
          Not in this team's workflow: {missingStatuses.map(([, n]) => n).join(", ")}.
          {missingStatuses.some(([k]) => k === "needs_owner")
            ? " Hand-offs will stay In Progress, assigned to the owner, with a comment starting 'Needs owner:'."
            : ""}
        </div>
      ) : null}

      <h4 style={{ margin: "8px 0 0" }}>Claude Code</h4>
      <div className="dw-grid2">
        <div className="field">
          <label>Permissions</label>
          <select
            value={v("permission_mode")}
            onChange={(e) => set({ permission_mode: e.target.value as "allowlist" | "bypass" })}
          >
            <option value="allowlist">Allowlist + accept edits (denied commands are listed on the run)</option>
            <option value="bypass">Bypass permissions (can run anything on this PC)</option>
          </select>
          <span className="field-hint">git push is always blocked.</span>
        </div>
        <div className="field">
          <label>Model (blank = Claude Code default)</label>
          <input value={v("model") ?? ""} onChange={(e) => set({ model: e.target.value })} />
        </div>
      </div>
      {v("permission_mode") === "allowlist" ? (
        <div className="field">
          <label>Allowed tools (comma-separated, Claude Code syntax)</label>
          <textarea rows={3} value={v("allowed_tools")} onChange={(e) => set({ allowed_tools: e.target.value })} />
        </div>
      ) : null}
    </div>
  );
}

function WorkerTerminals({ slug, handle, enabled }: { slug: string; handle: string; enabled: boolean }) {
  const [data, setData] = useState<Terminals | null>(null);
  const load = useCallback(async () => {
    try {
      setData(await devApi.terminals(slug, handle));
    } catch {
      /* the summary shows errors */
    }
  }, [slug, handle]);
  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(t);
  }, [load]);
  if (!data) return null;
  const stop = async (runId: string) => {
    const reason = window.prompt("Stop this run? Optional reason (goes on the ticket):", "");
    if (reason === null) return;
    await devApi.stop(slug, runId, reason || undefined);
    await load();
  };
  if (data.terminals.length === 0) {
    return (
      <div className="ct">
        <div className="ct-bar">
          <span className="ct-light" />
          <span className="ct-title">No one is working</span>
        </div>
        <div className="ct-body ct-dim">
          {enabled
            ? "Assign a ticket to Claude in Todo; a terminal opens here when a worker picks it up."
            : "Paused. Start picking up tickets, then assign one to Claude in Todo."}
        </div>
      </div>
    );
  }
  return (
    <div className={`ct-grid n${Math.min(data.terminals.length, 3)}`}>
      {data.terminals.map((t) => (
        <ClaudeTerminal key={t.run.id} slug={slug} run={t.run} transcript={t.transcript} onStop={() => void stop(t.run.id)} />
      ))}
    </div>
  );
}

export function DevWorkPage() {
  const { handle = "" } = useParams();
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [data, setData] = useState<DevSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await devApi.summary(slug, handle));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [slug, handle]);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(t);
  }, [load]);

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (!data) {
    return <div className="stack">{error ? <div className="error">{error}</div> : <p className="muted">Loading…</p>}</div>;
  }
  const { worker: w, stats } = data;
  const configured = Boolean(w.linear_installation_id && w.team_id && w.owner_linear_id && w.repo_path);
  const enabled = w.enabled === 1;
  const queue = w.queue;

  return (
    <div className="stack">
      <Link to={`/${slug}/dashboard/${handle}`} className="muted">
        ← {data.agent.display_name}'s dashboard
      </Link>
      <div className="page-header">
        <div>
          <h2 style={{ margin: 0 }}>
            {data.agent.display_name} · {data.agent.role_title}
          </h2>
          <p className="muted" style={{ margin: "2px 0 0" }}>
            {enabled ? (
              <span className="dw-chip ok">● Picking up work</span>
            ) : (
              <span className="dw-chip">Paused</span>
            )}{" "}
            Linear polled {ago(w.last_poll_ok_at)}
            {w.team_key ? ` · team ${w.team_key}` : ""}
            {w.viewer_name ? ` · acts as ${w.viewer_name}` : ""}
          </p>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="secondary"
            disabled={!enabled || busy !== null}
            onClick={() => void act("poll", () => devApi.pollNow(slug, handle))}
          >
            Check Linear now
          </button>
          <button
            type="button"
            className={enabled ? "secondary" : ""}
            disabled={(!configured && !enabled) || busy !== null}
            title={configured ? "" : "Finish the setup below first"}
            onClick={() => void act("enable", () => devApi.saveConfig(slug, handle, { enabled: !enabled }))}
          >
            {enabled ? "Pause" : "Start picking up tickets"}
          </button>
        </div>
      </div>
      {error ? <div className="error">{error}</div> : null}
      {w.last_poll_error ? <div className="dw-banner error">Linear: {w.last_poll_error}</div> : null}
      {!configured ? (
        <div className="dw-banner warn">Finish the setup below (Linear, team, your Linear account, repo), then start.</div>
      ) : null}

      <div className="dw-tiles">
        <div className="dw-tile">
          <div className="v">
            {stats.active} / {w.max_concurrent}
          </div>
          <div className="k">Running</div>
        </div>
        <div className="dw-tile">
          <div className="v">{stats.queued}</div>
          <div className="k">Queued</div>
        </div>
        <div className="dw-tile">
          <div className="v">{stats.handed_off}</div>
          <div className="k">Handed off (recent)</div>
        </div>
        <div className="dw-tile">
          <div className="v" style={stats.failed_24h ? { color: "var(--danger)" } : undefined}>
            {stats.failed_24h}
          </div>
          <div className="k">Failed · 24 h</div>
        </div>
        <div className="dw-tile">
          <div className="v">${stats.cost_24h.toFixed(2)}</div>
          <div className="k">24 h at API prices · {(stats.tokens_24h / 1_000_000).toFixed(1)}M tokens</div>
        </div>
      </div>

      {configured ? <WorkerTerminals slug={slug} handle={handle} enabled={enabled} /> : null}

      <div className="panel stack">
        <h3 style={{ margin: 0 }}>Running</h3>
        {data.active.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>
            Nothing running.
          </p>
        ) : (
          <table className="dw-table">
            <thead>
              <tr>
                <th>Ticket</th>
                <th>Status</th>
                <th>Time</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.active.map((r) => (
                <tr key={r.id}>
                  <td>
                    <TicketCell run={r} />
                  </td>
                  <td>
                    <span className={`dw-chip ${runTone(r.status)}`}>
                      {r.stop_requested ? "Stopping…" : RUN_STATUS_LABEL[r.status] ?? r.status}
                    </span>{" "}
                    <Link to={`/${slug}/dev/runs/${r.id}`}>open run</Link>
                  </td>
                  <td className="dw-nowrap">{duration(r.started_at ?? r.created_at, null)}</td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      type="button"
                      className="danger"
                      disabled={busy !== null || r.stop_requested === 1}
                      onClick={() => void act(`stop-${r.id}`, () => devApi.stop(slug, r.id))}
                    >
                      Stop
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel stack">
        <h3 style={{ margin: 0 }}>Queue</h3>
        {queue.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>
            {enabled ? "No tickets waiting." : "Paused. Start it to read the queue from Linear."}
          </p>
        ) : (
          <table className="dw-table">
            <tbody>
              {queue.map((q) => (
                <tr key={q.id}>
                  <td>
                    <TicketCell run={{ ticket_key: q.key, ticket_title: q.title, ticket_url: q.url }} />
                  </td>
                  <td>
                    <span className={`dw-chip ${q.class === "assigned" ? "acc" : ""}`}>
                      {q.class === "assigned" ? "assigned" : "agent-ready"}
                    </span>
                    {q.follow_up ? <span className="dw-chip" style={{ marginLeft: 4 }}>follow-up</span> : null}
                  </td>
                  <td className="muted">{q.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel stack">
        <h3 style={{ margin: 0 }}>Recent</h3>
        {data.recent.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>
            No runs yet.
          </p>
        ) : (
          <table className="dw-table">
            <tbody>
              {data.recent.map((r) => (
                <tr key={r.id}>
                  <td>
                    <TicketCell run={r} />
                  </td>
                  <td>
                    <span className={`dw-chip ${runTone(r.status)}`}>{RUN_STATUS_LABEL[r.status] ?? r.status}</span>
                  </td>
                  <td className="muted dw-nowrap">
                    {ago(r.ended_at)} · {duration(r.started_at, r.ended_at)} {cost(r) ? `· ${cost(r)}` : ""}
                  </td>
                  <td className="dw-nowrap" style={{ textAlign: "right" }}>
                    <Link to={`/${slug}/dev/runs/${r.id}`} className="btn secondary">
                      Open
                    </Link>{" "}
                    {r.status === "failed" || r.status === "timed_out" || r.status === "cancelled" ? (
                      <button
                        type="button"
                        className="secondary"
                        disabled={busy !== null}
                        onClick={() => void act(`retry-${r.id}`, () => devApi.retry(slug, r.id))}
                      >
                        Retry
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <SetupPanel slug={slug} handle={handle} summary={data} onSaved={() => void load()} />
    </div>
  );
}

export function DevWorkLink({ slug, handle }: { slug: string; handle: string }) {
  const [ok, setOk] = useState(false);
  useEffect(() => {
    devApi
      .summary(slug, handle)
      .then(() => setOk(true))
      .catch(() => setOk(false));
  }, [slug, handle]);
  if (!ok) return null;
  return (
    <Link to={`/${slug}/dashboard/${handle}/work`} className="btn">
      Work
    </Link>
  );
}
