import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { devsApi, type RunTileData } from "../api/devs";
import { devApi, duration, RUN_STATUS_LABEL, runTone } from "../api/devwork";
import { Entry } from "./ClaudeTerminal";

// A ticket run on the Devs page: its live transcript (headless, stream-json), a
// message box into its session, Stop, and "Continue in a terminal" once it ends.

const ACTIVE = ["queued", "claiming", "preparing", "running"];

export function RunTile({
  slug,
  data,
  focused,
  maximized,
  onFocus,
  onToggleMax,
  onChanged,
  onContinued,
}: {
  slug: string;
  data: RunTileData;
  focused: boolean;
  maximized: boolean;
  onFocus: () => void;
  onToggleMax: () => void;
  onChanged: () => void;
  onContinued: (devId: string) => void | Promise<void>;
}) {
  const { run, transcript } = data;
  const active = ACTIVE.includes(run.status);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [stick, setStick] = useState(true);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    const el = bodyRef.current;
    if (el && stick) el.scrollTop = el.scrollHeight;
  }, [transcript.total, stick]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setNote(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const send = () =>
    act(async () => {
      const r = await devsApi.message(slug, run.id, text);
      setText("");
      if (!r.posted_to_ticket) setNote("Sent to the run; couldn't copy it to the ticket.");
    });

  const hidden = transcript.total - transcript.entries.length;
  return (
    <div className={`dt dt-run ${focused ? "focused" : ""}`} onMouseDown={onFocus}>
      <div className="dt-bar" onDoubleClick={onToggleMax}>
        <span className={`dt-light ${active ? "live" : runTone(run.status) === "ok" ? "done" : "exited"}`} />
        <Link to={`/${slug}/dev/runs/${run.id}`} className="dt-name dt-runtitle" title="Open the full run page">
          <span className="dt-key">{run.ticket_key}</span> {run.ticket_title}
        </Link>
        <span className="dt-cwd">
          {RUN_STATUS_LABEL[run.status] ?? run.status} · {duration(run.started_at ?? run.created_at, run.ended_at)}
        </span>
        <span className="dt-spacer" />
        {run.ticket_url ? (
          <a className="dt-btn dt-link" href={run.ticket_url} target="_blank" rel="noreferrer" title="Open the ticket in Linear">
            Linear ↗
          </a>
        ) : null}
        {active ? (
          <button
            type="button"
            className="dt-btn dt-stop"
            disabled={busy || run.stop_requested === 1}
            title="Stop this run (the branch is kept)"
            onClick={() => void act(() => devApi.stop(slug, run.id, "Stopped from the Devs page"))}
          >
            {run.stop_requested ? "Stopping…" : "Stop"}
          </button>
        ) : (
          <button
            type="button"
            className="dt-btn"
            disabled={busy}
            title="Remove this tile"
            onClick={() => void act(() => devsApi.dismiss(slug, run.id))}
          >
            Dismiss
          </button>
        )}
        <button type="button" className="dt-btn" title={maximized ? "Back to four" : "Fill the screen"} onClick={onToggleMax}>
          {maximized ? "⊞" : "⛶"}
        </button>
      </div>
      <div
        className="ct-body dt-runbody"
        ref={bodyRef}
        onScroll={() => {
          const el = bodyRef.current;
          if (el) setStick(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
        }}
      >
        {transcript.prompt ? <div className="ct-prompt">&gt; {transcript.prompt}</div> : null}
        {hidden > 0 ? <div className="ct-dim">… {hidden} earlier lines (open the run for all)</div> : null}
        {transcript.entries.map((e, i) => (
          <Entry key={i} e={e} live={active} />
        ))}
        {transcript.entries.length === 0 ? (
          <div className="ct-dim">{active ? "Starting Claude Code…" : "No output."}</div>
        ) : null}
      </div>
      <div className="dt-runfoot">
        {active ? (
          <form
            className="dt-msg"
            onSubmit={(e) => {
              e.preventDefault();
              if (text.trim() && run.accepts_messages) void send();
            }}
          >
            <input
              value={text}
              disabled={!run.accepts_messages || busy}
              placeholder={
                run.accepts_messages
                  ? "Message this run (also posted on the ticket)…"
                  : run.status === "running"
                  ? "This run isn't taking messages (finishing, or started before a restart)"
                  : "Messages open once Claude Code is running"
              }
              onChange={(e) => setText(e.target.value)}
            />
            <button type="submit" disabled={!text.trim() || !run.accepts_messages || busy}>
              Send
            </button>
          </form>
        ) : (
          <div className="dt-msg">
            <span className="dt-ended">
              {run.outcome_summary || run.failure_reason || `Run ${RUN_STATUS_LABEL[run.status]?.toLowerCase() ?? run.status}.`}
            </span>
            {run.session_id && run.worktree_path ? (
              <button
                type="button"
                disabled={busy}
                title="Open an interactive terminal in this run's folder that resumes its Claude session"
                onClick={() =>
                  void act(async () => {
                    const dev = await devsApi.continueRun(slug, run.id);
                    await onContinued(dev.id);
                  })
                }
              >
                Continue in a terminal
              </button>
            ) : null}
          </div>
        )}
        {note ? <div className="dt-note">{note}</div> : null}
      </div>
    </div>
  );
}
