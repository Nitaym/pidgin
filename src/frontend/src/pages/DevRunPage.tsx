import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { devApi, duration, RUN_STATUS_LABEL, runTone, type RunDetail } from "../api/devwork";
import { useApp } from "../context/AppContext";
import { ClaudeTerminal } from "../components/ClaudeTerminal";
import "../styles/devwork.css";

// One Claude Code run on one ticket (specs/DEVELOPER_WORKER_SPEC.html §4.6).

const ACTIVE = ["queued", "claiming", "preparing", "running"];

function fmt(n: number | null): string {
  if (n == null) return "–";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${Math.round(n / 1000)}k`;
  return String(n);
}

export function DevRunPage() {
  const { runId = "" } = useParams();
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [data, setData] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showStderr, setShowStderr] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await devApi.run(slug, runId));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [slug, runId]);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(t);
  }, [load]);

  if (!data) {
    return <div className="stack">{error ? <div className="error">{error}</div> : <p className="muted">Loading…</p>}</div>;
  }
  const { run, events } = data;
  const active = ACTIVE.includes(run.status);

  const stop = async () => {
    const reason = window.prompt("Stop this run? Optional reason (goes on the ticket):", "");
    if (reason === null) return;
    setBusy(true);
    try {
      await devApi.stop(slug, run.id, reason || undefined);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const retry = async () => {
    setBusy(true);
    try {
      await devApi.retry(slug, run.id);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      {data.agent ? (
        <Link to={`/${slug}/dashboard/${data.agent.handle}/work`} className="muted">
          ← {data.agent.display_name} · Work
        </Link>
      ) : null}
      <div className="page-header">
        <div>
          <h2 style={{ margin: 0 }}>
            <span className="dw-key">{run.ticket_key}</span>
            {run.ticket_title} · attempt {run.attempt}
          </h2>
        </div>
        <div className="page-header-actions">
          {run.ticket_url ? (
            <a href={run.ticket_url} target="_blank" rel="noreferrer" className="btn secondary">
              Open in Linear ↗
            </a>
          ) : null}
          {active ? (
            <button type="button" className="danger" disabled={busy || run.stop_requested === 1} onClick={() => void stop()}>
              {run.stop_requested ? "Stopping…" : "Stop"}
            </button>
          ) : null}
          {["failed", "timed_out", "cancelled"].includes(run.status) ? (
            <button type="button" disabled={busy} onClick={() => void retry()}>
              Retry
            </button>
          ) : null}
        </div>
      </div>
      {error ? <div className="error">{error}</div> : null}

      <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span className={`dw-chip ${runTone(run.status)}`}>
          {RUN_STATUS_LABEL[run.status] ?? run.status} · {duration(run.started_at ?? run.created_at, run.ended_at)}
        </span>
        {run.branch ? <span className="dw-chip">{run.branch}</span> : null}
        {run.base_sha ? <span className="dw-chip">from {run.base_sha.slice(0, 8)}</span> : null}
        <span className="muted">
          {fmt(run.input_tokens)} in · {fmt(run.output_tokens)} out · {fmt(run.cache_read_tokens)} cache
          {run.cost_usd != null ? ` · $${run.cost_usd.toFixed(2)}` : ""}
          {run.num_turns != null ? ` · ${run.num_turns} turns` : ""}
        </span>
      </div>
      {run.failure_reason ? <div className="dw-banner error">{run.failure_reason}</div> : null}
      {run.outcome_summary ? (
        <div className="panel">
          <strong>{run.outcome === "done" ? "Done" : run.outcome ? "Handed off" : "Last message"}:</strong>{" "}
          {run.outcome_summary}
        </div>
      ) : null}

      <div className="dw-split">
        <div className="stack">
          <ClaudeTerminal slug={slug} run={run} transcript={data.transcript} tall onStop={() => void stop()} />
          {data.stderr ? (
            <div>
              <button type="button" className="ghost" onClick={() => setShowStderr((s) => !s)}>
                {showStderr ? "Hide" : "Show"} stderr
              </button>
              {showStderr ? <pre className="dw-log">{data.stderr}</pre> : null}
            </div>
          ) : null}
        </div>
        <div className="panel stack">
          <h3 style={{ margin: 0 }}>Timeline</h3>
          <ul className="dw-tl">
            {events.map((e) => (
              <li key={e.id} className={e.kind}>
                <span className="t">{new Date(e.occurred_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                {e.message}
                {e.kind === "commits" && e.data_json ? (
                  <div className="muted" style={{ fontFamily: "ui-monospace, Consolas, monospace", fontSize: 11.5 }}>
                    {(JSON.parse(e.data_json) as { commits: string[] }).commits.map((c) => (
                      <div key={c}>{c}</div>
                    ))}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
          {run.worktree_path ? (
            <p className="muted" style={{ margin: 0, wordBreak: "break-all" }}>
              Worktree: <code>{run.worktree_path}</code>
            </p>
          ) : null}
          {run.log_dir ? (
            <p className="muted" style={{ margin: 0, wordBreak: "break-all" }}>
              Files: <code>{run.log_dir}</code>
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
