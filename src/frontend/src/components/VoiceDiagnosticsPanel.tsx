import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { TimingMark } from "../hooks/useVoiceSession";

export type MarkMap = Partial<Record<TimingMark, number>>;
export interface LlmMarks { start?: number; firstByte?: number; done?: number }

interface SpanDef {
  key: string;
  label: string;
  color: string;
  start?: number;
  end?: number;
}

interface Props {
  marks: MarkMap;
  llm: LlmMarks;
  /** A turn is in progress — animate running bars. */
  live: boolean;
  slug: string;
  /** Turn id of the latest completed turn, for the LLM I/O inspector. */
  turnId?: string;
  /** The user's last message, to detect duplication in the prompt. */
  userText?: string;
}

const round = (ms: number) => Math.round(ms);

export function VoiceDiagnosticsPanel({ marks, llm, live, slug, turnId, userText }: Props) {
  const [now, setNow] = useState(0);

  // Realtime clock for growing in-progress bars.
  useEffect(() => {
    if (!live) return;
    let id = 0;
    const tick = () => { setNow(performance.now()); id = requestAnimationFrame(tick); };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [live]);

  const spans: SpanDef[] = [
    { key: "stt", label: "STT", color: "#14b8a6", start: marks.speechEnd, end: marks.transcript },
    { key: "llmFirst", label: "LLM · first token", color: "#f59e0b", start: llm.start, end: llm.firstByte },
    { key: "llmTotal", label: "LLM · complete", color: "#d97706", start: llm.start, end: llm.done },
    { key: "ttsFirst", label: "TTS · first byte", color: "#3b82f6", start: marks.synthesizeStart, end: marks.ttsFirstByte },
    { key: "ttsTotal", label: "TTS · complete", color: "#22c55e", start: marks.synthesizeStart, end: marks.audioDone },
  ];

  const t0 = marks.speechEnd ?? marks.recordingStart ?? llm.start ?? marks.synthesizeStart;
  let tMax = t0 ?? 0;
  for (const sp of spans) {
    if (sp.start !== undefined) tMax = Math.max(tMax, sp.start);
    if (sp.end !== undefined) tMax = Math.max(tMax, sp.end);
  }
  if (live && now) tMax = Math.max(tMax, now);
  const scale = Math.max(tMax - (t0 ?? 0), 1);
  const hasTimeline = t0 !== undefined;

  const audible = marks.playbackStart ?? marks.audioDone;
  const overlapMs = (llm.done !== undefined && audible !== undefined) ? llm.done - audible : undefined;

  // Pre-compute rows so we can show Δ (time since previous line).
  const rows = spans.map((sp) => {
    const started = sp.start !== undefined && t0 !== undefined;
    const ended = sp.end !== undefined;
    const e = ended ? sp.end! : (live ? now : undefined);
    const showBar = started && e !== undefined;
    const left = showBar ? ((sp.start! - t0!) / scale) * 100 : 0;
    const width = showBar ? Math.max(((e! - sp.start!) / scale) * 100, 0.6) : 0;
    const abs = showBar ? e! - t0! : undefined;
    const isRunning = started && !ended && live;
    return { sp, started, showBar, left, width, abs, isRunning };
  });

  return (
    <div className="stack" style={{ gap: 12 }}>
      {/* ── Pipeline timeline ── */}
      {hasTimeline ? (
        <div className="stack" style={{ gap: 4 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--text-tertiary)" }}>
            <div style={{ width: 130, flexShrink: 0 }}>Stage</div>
            <div style={{ flex: 1, display: "flex", justifyContent: "space-between" }}>
              <span>0 ms</span><span>{round(scale)} ms</span>
            </div>
            <div style={{ width: 64, flexShrink: 0, textAlign: "right" }}>Δ</div>
            <div style={{ width: 78, flexShrink: 0, textAlign: "right" }}>from speech</div>
          </div>
          {(() => {
            let prevAbs: number | undefined;
            return rows.map((r) => {
              const dt = r.abs !== undefined && prevAbs !== undefined ? r.abs - prevAbs : r.abs;
              if (r.abs !== undefined) prevAbs = r.abs;
              return (
                <div key={r.sp.key} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ width: 130, flexShrink: 0, fontSize: 12, color: "var(--text-secondary)" }}>
                    {r.sp.label}
                  </div>
                  <div style={{ position: "relative", flex: 1, height: 16, background: "var(--bg-base)", borderRadius: 3 }}>
                    {r.showBar && (
                      <div
                        className={r.isRunning ? "bar--running" : undefined}
                        style={{
                          position: "absolute", top: 0, bottom: 0,
                          left: `${r.left}%`, width: `${r.width}%`,
                          background: r.sp.color, borderRadius: 3,
                          opacity: r.isRunning ? 0.85 : 1,
                        }}
                      />
                    )}
                  </div>
                  <div style={{
                    width: 64, flexShrink: 0, textAlign: "right", fontSize: 12,
                    fontVariantNumeric: "tabular-nums", color: "var(--text-tertiary)",
                  }}>
                    {dt !== undefined ? `${dt >= 0 ? "+" : "−"}${round(Math.abs(dt))}` : ""}
                  </div>
                  <div style={{
                    width: 78, flexShrink: 0, textAlign: "right", fontSize: 12,
                    fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap",
                    color: r.isRunning ? r.sp.color : "var(--text-primary)",
                    fontWeight: r.isRunning ? 600 : 400,
                  }}>
                    {!r.started
                      ? (r.sp.key === "stt" ? "N/A" : "—")
                      : r.isRunning ? `▶ ${round(r.abs!)}` : `${round(r.abs!)} ms`}
                  </div>
                </div>
              );
            });
          })()}
        </div>
      ) : (
        <p style={{ margin: 0, fontSize: 13, color: "var(--text-tertiary)" }}>
          Speak to the agent — pipeline timings will appear here.
        </p>
      )}

      {overlapMs !== undefined && !live && (
        <p style={{
          margin: 0, fontSize: 13, fontWeight: 600,
          color: overlapMs >= 0 ? "var(--success)" : "var(--error)",
        }}>
          {overlapMs >= 0
            ? `✓ Pipelined: first audio played ${round(overlapMs)} ms before the response finished`
            : `✗ Not pipelined: first audio started ${round(-overlapMs)} ms after the response finished`}
        </p>
      )}

      <LlmInspector slug={slug} turnId={turnId} userText={userText} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// LLM I/O inspector — fetches the turn detail and shows exactly what the model
// received (assembled prompt) and returned.
// ---------------------------------------------------------------------------

interface PromptMsg { role: string; content: string }
interface InspectorData {
  input: PromptMsg[];
  output: string;
  stopReason?: string;
  inputTokens?: number;
  outputTokens?: number;
  invocations: number;
  dupCount: number;
}

function LlmInspector({ slug, turnId, userText }: { slug: string; turnId?: string; userText?: string }) {
  const [data, setData] = useState<InspectorData | null>(null);
  const [error, setError] = useState("");
  const lastTurn = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!turnId || !slug || turnId === lastTurn.current) return;
    lastTurn.current = turnId;
    setError("");
    api.getTurn(slug, turnId)
      .then((detail) => {
        const d = detail as {
          model_invocations?: Array<{
            request_messages_json?: string;
            response_json?: string;
            input_tokens?: number;
            output_tokens?: number;
          }>;
        };
        const invs = d.model_invocations ?? [];
        if (!invs.length) { setData(null); return; }
        const first = invs[0];
        const last = invs[invs.length - 1];
        const input: PromptMsg[] = first.request_messages_json ? JSON.parse(first.request_messages_json) : [];
        let output = "";
        let stopReason: string | undefined;
        if (last.response_json) {
          const r = JSON.parse(last.response_json) as { assistant_text?: string; stop_reason?: string };
          output = r.assistant_text ?? "";
          stopReason = r.stop_reason;
        }
        const dupCount = userText
          ? input.filter((m) => m.role === "user" && m.content.trim() === userText.trim()).length
          : 0;
        setData({
          input, output, stopReason,
          inputTokens: last.input_tokens, outputTokens: last.output_tokens,
          invocations: invs.length, dupCount,
        });
      })
      .catch((e: Error) => setError(`Couldn't load turn detail: ${e.message}`));
  }, [slug, turnId, userText]);

  if (error) return <p style={{ margin: 0, fontSize: 13, color: "var(--error)" }}>{error}</p>;
  if (!data) return null;

  return (
    <div className="stack" style={{ gap: 8 }}>
      {data.dupCount > 1 && (
        <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "var(--error)" }}>
          ⚠ Your message appears {data.dupCount}× in the LLM input — duplication bug present.
        </p>
      )}
      {data.dupCount === 1 && (
        <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "var(--success)" }}>
          ✓ Your message appears exactly once in the LLM input.
        </p>
      )}

      <details>
        <summary style={{ cursor: "pointer", fontSize: 13, fontWeight: 600 }}>
          LLM input — what the model received ({data.input.length} messages, {data.invocations} invocation{data.invocations === 1 ? "" : "s"})
        </summary>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
          {data.input.map((m, i) => (
            <div key={i} style={{
              fontSize: 12, background: "var(--bg-base)", border: "1px solid var(--border)",
              borderRadius: 6, padding: "6px 8px",
            }}>
              <div style={{ color: "var(--text-tertiary)", textTransform: "uppercase", fontSize: 10, letterSpacing: 0.5 }}>
                {m.role}
              </div>
              <div style={{ whiteSpace: "pre-wrap", color: "var(--text-secondary)" }}>{m.content}</div>
            </div>
          ))}
        </div>
      </details>

      <details>
        <summary style={{ cursor: "pointer", fontSize: 13, fontWeight: 600 }}>
          LLM output {data.stopReason ? `(${data.stopReason})` : ""}
          {data.inputTokens !== undefined ? ` · ${data.inputTokens}→${data.outputTokens} tok` : ""}
        </summary>
        <div style={{
          fontSize: 12, whiteSpace: "pre-wrap", marginTop: 8, color: "var(--text-secondary)",
          background: "var(--bg-base)", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 8px",
        }}>
          {data.output || <span style={{ color: "var(--text-tertiary)" }}>(no assistant text)</span>}
        </div>
      </details>
    </div>
  );
}
