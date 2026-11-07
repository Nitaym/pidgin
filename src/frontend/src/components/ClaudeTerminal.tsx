import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { duration, RUN_STATUS_LABEL, runTone, type CodeRun, type Transcript, type TranscriptEntry } from "../api/devwork";

// A Claude Code worker's run, drawn the way Claude Code looks in a terminal.

const ACTIVE = ["queued", "claiming", "preparing", "running"];

export function Entry({ e, live }: { e: TranscriptEntry; live: boolean }) {
  if (e.k === "init") return <div className="ct-dim">{e.text}</div>;
  if (e.k === "say")
    return (
      <div className="ct-say">
        <span className="ct-dot">●</span>
        <span>{e.text}</span>
      </div>
    );
  if (e.k === "user")
    return (
      <div className="ct-user">
        <div>
          <span className="ct-caret">&gt;</span>
          <span>{e.text}</span>
        </div>
        <div className="ct-dim ct-from">
          {e.via === "pidgin" ? `from Pidgin${e.who ? ` · ${e.who}` : ""}` : `from ${e.who ? `${e.who}'s ` : "a "}Linear comment`}
          {e.url ? (
            <>
              {" · "}
              <a href={e.url} target="_blank" rel="noreferrer">
                open comment
              </a>
            </>
          ) : null}
        </div>
      </div>
    );
  if (e.k === "todos")
    return (
      <div className="ct-tool">
        <div>
          <span className="ct-dot ok">●</span>
          <b>Update Todos</b>
        </div>
        <div className="ct-out">
          {e.items.map((t, i) => (
            <div key={i} className={`ct-todo ${t.status}`}>
              {t.status === "completed" ? "☒" : t.status === "in_progress" ? "◐" : "☐"} {t.text}
            </div>
          ))}
        </div>
      </div>
    );
  if (e.k === "tool")
    return (
      <div className="ct-tool">
        <div>
          <span className={`ct-dot ${e.status === "pending" && !live ? "" : e.status}`}>●</span>
          <b>{e.name}</b>
          {e.arg ? <span className="ct-arg">({e.arg})</span> : null}
        </div>
        {e.status === "pending" ? (
          <div className="ct-out ct-dim">⎿ {live ? "running…" : "interrupted"}</div>
        ) : (
          <div className={`ct-out ${e.status === "error" ? "ct-err" : ""}`}>
            {e.out.map((line, i) => (
              <div key={i}>
                {i === 0 ? "⎿ " : "  "}
                {line}
              </div>
            ))}
            {e.more > 0 ? <div className="ct-dim">  … +{e.more} lines</div> : null}
          </div>
        )}
      </div>
    );
  return <div className={e.ok ? "ct-end ok" : "ct-end bad"}>■ {e.text}</div>;
}

export function ClaudeTerminal({
  slug,
  run,
  transcript,
  tall = false,
  onStop,
}: {
  slug: string;
  run: CodeRun;
  transcript: Transcript;
  tall?: boolean;
  onStop?: () => void;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const [stick, setStick] = useState(true);
  const active = ACTIVE.includes(run.status);

  useEffect(() => {
    const el = bodyRef.current;
    if (el && stick) el.scrollTop = el.scrollHeight;
  }, [transcript.total, transcript.entries, stick]);

  const onScroll = () => {
    const el = bodyRef.current;
    if (el) setStick(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };

  const hidden = transcript.total - transcript.entries.length;
  return (
    <div className={`ct ${tall ? "tall" : ""}`}>
      <div className="ct-bar">
        <span className={`ct-light ${active ? "live" : runTone(run.status)}`} />
        <Link to={`/${slug}/dev/runs/${run.id}`} className="ct-title" title="Open this run">
          <span className="ct-key">{run.ticket_key}</span> {run.ticket_title}
        </Link>
        <span className="ct-meta">
          {RUN_STATUS_LABEL[run.status] ?? run.status} · {duration(run.started_at ?? run.created_at, run.ended_at)}
          {run.branch ? ` · ${run.branch}` : ""}
        </span>
        {onStop && active ? (
          <button type="button" className="ct-stop" disabled={run.stop_requested === 1} onClick={onStop}>
            {run.stop_requested ? "Stopping…" : "Stop"}
          </button>
        ) : null}
      </div>
      <div className="ct-body" ref={bodyRef} onScroll={onScroll}>
        {transcript.prompt ? <div className="ct-prompt">&gt; {transcript.prompt}</div> : null}
        {hidden > 0 ? <div className="ct-dim">… {hidden} earlier steps (open the run for all)</div> : null}
        {transcript.entries.length === 0 ? (
          <div className="ct-dim">
            {run.status === "claiming" ? "Claiming the ticket…" : run.status === "preparing" ? "Preparing the worktree…" : "No output yet."}
          </div>
        ) : null}
        {transcript.entries.map((e, i) => (
          <Entry key={hidden + i} e={e} live={active} />
        ))}
        {active && run.status === "running" ? <div className="ct-cursor">✻ working…</div> : null}
      </div>
    </div>
  );
}
