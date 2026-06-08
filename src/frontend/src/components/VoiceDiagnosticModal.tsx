import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Agent } from "../api/client";
import { useApp } from "../context/AppContext";
import { useVoiceSession, type TimingMark } from "../hooks/useVoiceSession";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function VoiceDiagnosticModal({ open, onClose }: Props) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(0,0,0,0.6)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 16,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="panel stack"
        style={{
          width: "min(900px, 100%)", maxHeight: "90vh", overflow: "auto",
          padding: 24, gap: 20,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>Voice Diagnostics</h3>
          <button
            type="button"
            className="secondary"
            onClick={onClose}
            style={{ padding: "4px 12px", fontSize: 13 }}
          >
            ✕ Close
          </button>
        </div>

        <p className="muted" style={{ margin: 0, fontSize: 13 }}>
          Tests your configured STT and TTS providers. Providers use the settings saved on the Voice page.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <STTDiagnostic />
          <TTSDiagnostic />
        </div>

        <LatencyDiagnostic />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Latency diagnostic — full conversational loop, broken out by stage.
// Reuses useVoiceSession (the exact code the chat uses) so the measured
// path is identical to a real voice turn.
// ---------------------------------------------------------------------------

type MarkMap = Partial<Record<TimingMark, number>>;
interface LlmMarks { start?: number; firstByte?: number; done?: number }

interface SpanDef {
  key: string;
  label: string;
  color: string;
  start?: number;
  end?: number;
}

const round = (ms: number) => Math.round(ms);

function LatencyDiagnostic() {
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";

  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentHandle, setAgentHandle] = useState("");
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState("");
  const [transcript, setTranscript] = useState("");
  const [response, setResponse] = useState("");

  // Live timing state — drives both the table and the realtime timeline.
  const [marks, setMarks] = useState<MarkMap>({});
  const [llm, setLlm] = useState<LlmMarks>({});
  const [now, setNow] = useState(0);

  const synthRef = useRef<(t: string) => void>(() => {});
  const feedRef = useRef<(d: string) => void>(() => {});
  const finishRef = useRef<() => void>(() => {});
  const sourceRef = useRef<EventSource | null>(null);
  const handledRef = useRef(false); // one transcript → one send per run

  useEffect(() => {
    if (!slug) return;
    api.listAgents(slug)
      .then((a) => {
        setAgents(a);
        setAgentHandle((cur) => cur || (a[0]?.handle ?? ""));
      })
      .catch(() => {});
  }, [slug]);

  const onTimingMark = useCallback((m: TimingMark, t: number) => {
    setMarks((prev) => ({ ...prev, [m]: t }));
  }, []);

  // Realtime clock — re-render running bars while a turn is in progress.
  useEffect(() => {
    if (!running) return;
    let id = 0;
    const tick = () => { setNow(performance.now()); id = requestAnimationFrame(tick); };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [running]);

  // The LLM stage — reuses api.sendAgentMessage + EventSource, exactly as the chat.
  const runLlmThenSpeak = useCallback(async (text: string) => {
    setTranscript(text);
    setResponse("");
    setLlm({});

    if (!slug || !agentHandle) {
      setStatus("No agent selected — echoing transcript to TTS (STT + TTS only)");
      synthRef.current(text);
      return;
    }

    setStatus("Waiting for agent…");
    setLlm({ start: performance.now() });
    try {
      const data = await api.sendAgentMessage(slug, agentHandle, text, true);
      const streamPath = data.stream_url ?? `/${slug}/api/turns/stream/${data.event_id}`;
      let full = "";
      const source = new EventSource(streamPath);
      sourceRef.current = source;
      source.onmessage = (msg) => {
        const parsed = JSON.parse(msg.data) as { type: string; delta?: string; message?: string };
        if (parsed.type === "text_delta" && parsed.delta) {
          setLlm((p) => (p.firstByte === undefined ? { ...p, firstByte: performance.now() } : p));
          full += parsed.delta;
          setResponse(full);
          // Pipeline TTS: synthesize sentences/clauses as they stream in.
          feedRef.current(parsed.delta);
        } else if (parsed.type === "error") {
          source.close();
          setStatus(`Agent error: ${parsed.message ?? "unknown"}`);
          setRunning(false);
        } else if (parsed.type === "invocation_end") {
          setLlm((p) => ({ ...p, done: performance.now() }));
          source.close();
          sourceRef.current = null;
          setStatus("Synthesising / speaking…");
          finishRef.current();
        }
      };
      source.onerror = () => {
        source.close();
        sourceRef.current = null;
        setStatus("Agent stream lost");
        setRunning(false);
      };
    } catch (err) {
      setStatus(`Agent send failed: ${(err as Error).message}`);
      setRunning(false);
    }
  }, [slug, agentHandle]);

  const voice = useVoiceSession({
    onTimingMark,
    onTranscript: (text) => {
      if (handledRef.current) return; // ignore further transcripts this run
      handledRef.current = true;
      void runLlmThenSpeak(text);
    },
    onAudioDone: () => { setRunning(false); setStatus("Done"); },
    onError: (msg) => { setStatus(`Error: ${msg}`); setRunning(false); },
  });

  useEffect(() => {
    synthRef.current = voice.synthesize;
    feedRef.current = voice.feedText;
    finishRef.current = voice.finishSpeaking;
  }, [voice.synthesize, voice.feedText, voice.finishSpeaking]);

  const start = useCallback(async () => {
    handledRef.current = false;
    setMarks({});
    setLlm({});
    setTranscript("");
    setResponse("");
    setRunning(true);
    setStatus("Warming up…");
    const ok = await voice.warmup();
    if (!ok) { setStatus("Warmup failed — is the backend running?"); setRunning(false); return; }
    setStatus("Listening… speak, then pause (or press Stop)");
    void voice.startRecording();
  }, [voice]);

  const stop = useCallback(() => {
    // Stop everything: the LLM stream, the mic, the TTS playback and the socket.
    sourceRef.current?.close();
    sourceRef.current = null;
    voice.stopRecording();
    voice.disconnect(); // closes the WS → backend stops sending; also stops playback
    setRunning(false);
    setStatus("Stopped");
  }, [voice]);

  // ── Build the 5 timeline spans ──
  const spans: SpanDef[] = [
    { key: "stt", label: "STT", color: "#14b8a6", start: marks.speechEnd, end: marks.transcript },
    { key: "llmFirst", label: "LLM · first token", color: "#f59e0b", start: llm.start, end: llm.firstByte },
    { key: "llmTotal", label: "LLM · complete", color: "#d97706", start: llm.start, end: llm.done },
    { key: "ttsFirst", label: "TTS · first byte", color: "#3b82f6", start: marks.synthesizeStart, end: marks.ttsFirstByte },
    { key: "ttsTotal", label: "TTS · complete", color: "#22c55e", start: marks.synthesizeStart, end: marks.audioDone },
  ];

  // Origin for absolute times: speech end when we have it (Whisper), else the
  // earliest available mark so the timeline still has a zero.
  const t0 = marks.speechEnd ?? marks.recordingStart ?? llm.start ?? marks.synthesizeStart;
  let tMax = t0 ?? 0;
  for (const sp of spans) {
    if (sp.start !== undefined) tMax = Math.max(tMax, sp.start);
    if (sp.end !== undefined) tMax = Math.max(tMax, sp.end);
  }
  if (running && now) tMax = Math.max(tMax, now);
  const scale = Math.max(tMax - (t0 ?? 0), 1);
  const hasTimeline = t0 !== undefined;

  const audible = marks.playbackStart ?? marks.audioDone;
  const overlapMs = (llm.done !== undefined && audible !== undefined) ? llm.done - audible : undefined;

  return (
    <section className="panel stack" style={{ gap: 12 }}>
      <h3 style={{ margin: 0 }}>Full-loop latency</h3>
      <p className="muted" style={{ margin: 0, fontSize: 13 }}>
        Runs a real voice turn through the same code the chat uses, timing each stage live.
        Speak a short phrase, then pause. STT timing requires the
        <strong> OpenAI Whisper</strong> STT mode (Realtime / Web Speech have no client-known speech end).
      </p>

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <label style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          Agent:&nbsp;
          <select value={agentHandle} onChange={(e) => setAgentHandle(e.target.value)} disabled={running}>
            <option value="">— none (STT + TTS only) —</option>
            {agents.map((a) => (
              <option key={a.handle} value={a.handle}>{a.display_name} (@{a.handle})</option>
            ))}
          </select>
        </label>

        <button type="button" onClick={() => void (running ? stop() : start())} disabled={voice.warming}>
          {voice.warming
            ? <><span className="spinner" /> Warming up…</>
            : running ? "⏹ Stop" : "▶ Run latency test"}
        </button>
      </div>

      {status && (
        <p style={{ margin: 0, fontSize: 13, color: status.startsWith("Error") ? "var(--error)" : "var(--text-secondary)" }}>
          {status}
        </p>
      )}

      {/* ── Realtime waterfall timeline ── */}
      {hasTimeline && (() => {
        // Pre-compute each row's absolute end time (from the origin) so we can
        // also derive Δ (time since the previous line).
        const rows = spans.map((sp) => {
          const started = sp.start !== undefined && t0 !== undefined;
          const ended = sp.end !== undefined;
          const e = ended ? sp.end! : (running ? now : undefined);
          const showBar = started && e !== undefined;
          const left = showBar ? ((sp.start! - t0!) / scale) * 100 : 0;
          const width = showBar ? Math.max(((e! - sp.start!) / scale) * 100, 0.6) : 0;
          const abs = showBar ? e! - t0! : undefined; // absolute time from speech end
          const isRunning = started && !ended && running;
          return { sp, started, showBar, left, width, abs, isRunning };
        });

        let prevAbs: number | undefined;
        return (
          <div className="stack" style={{ gap: 4 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--text-tertiary)" }}>
              <div style={{ width: 130, flexShrink: 0 }}>Stage</div>
              <div style={{ flex: 1, display: "flex", justifyContent: "space-between" }}>
                <span>0 ms</span><span>{round(scale)} ms</span>
              </div>
              <div style={{ width: 64, flexShrink: 0, textAlign: "right" }}>Δ</div>
              <div style={{ width: 78, flexShrink: 0, textAlign: "right" }}>from speech</div>
            </div>
            {rows.map((r) => {
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
            })}
          </div>
        );
      })()}

      {overlapMs !== undefined && !running && (
        <p style={{
          margin: 0, fontSize: 13, fontWeight: 600,
          color: overlapMs >= 0 ? "var(--success)" : "var(--error)",
        }}>
          {overlapMs >= 0
            ? `✓ Pipelined: first audio played ${round(overlapMs)} ms before the response finished`
            : `✗ Not pipelined: first audio started ${round(-overlapMs)} ms after the response finished`}
        </p>
      )}

      {(transcript || response) && (
        <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          {transcript && <p style={{ margin: "0 0 4px" }}><strong>You:</strong> {transcript}</p>}
          {response && <p style={{ margin: 0 }}><strong>Agent:</strong> {response}</p>}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// STT diagnostic — mic button, live transcript output
// ---------------------------------------------------------------------------

function STTDiagnostic() {
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [interim, setInterim] = useState("");
  const [status, setStatus] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const srRef = useRef<SpeechRecognition | null>(null);
  const pcmRef = useRef<ScriptProcessorNode | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);

  const sttBackend = localStorage.getItem("voice_stt") ?? "openai";

  const stop = useCallback(() => {
    srRef.current?.stop();
    srRef.current = null;
    mediaRef.current?.stop();
    mediaRef.current = null;
    pcmRef.current?.disconnect();
    pcmRef.current = null;
    ctxRef.current?.close();
    ctxRef.current = null;
    wsRef.current?.close();
    wsRef.current = null;
    setListening(false);
    setInterim("");
  }, []);

  const start = useCallback(async () => {
    setTranscript("");
    setInterim("");
    setStatus("");

    if (sttBackend === "web_speech") {
      const SR = window.SpeechRecognition ??
        (window as unknown as { webkitSpeechRecognition: typeof SpeechRecognition }).webkitSpeechRecognition;
      if (!SR) { setStatus("Web Speech API not supported in this browser."); return; }
      const sr = new SR();
      srRef.current = sr;
      sr.continuous = true;
      sr.interimResults = true;
      sr.lang = "en-US";
      sr.onresult = (e: SpeechRecognitionEvent) => {
        let inter = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          if (e.results[i].isFinal) {
            setTranscript((t) => t + (t ? " " : "") + e.results[i][0].transcript.trim());
            setInterim("");
          } else {
            inter += e.results[i][0].transcript;
          }
        }
        if (inter) setInterim(inter);
      };
      sr.onerror = (e: SpeechRecognitionErrorEvent) => {
        if (e.error !== "no-speech") setStatus(`Error: ${e.error}`);
      };
      sr.start();
      setListening(true);
      setStatus("Listening via browser…");
      return;
    }

    // Whisper or Realtime — connect backend WS
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const tts = localStorage.getItem("voice_tts") ?? "elevenlabs";
    const ws = new WebSocket(`${proto}://${location.host}/api/voice/ws?stt=${sttBackend}&tts=${tts}`);
    wsRef.current = ws;

    // Capture errors sent before WS open (e.g. missing API key)
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data as string) as { type: string; text?: string; message?: string };
      if (msg.type === "transcript") {
        setTranscript((t) => t + (t ? " " : "") + (msg.text ?? ""));
        setInterim("");
      } else if (msg.type === "transcript_delta") {
        setInterim((i) => i + (msg.text ?? ""));
      } else if (msg.type === "error") {
        setStatus(`Error: ${msg.message ?? "unknown"}`);
        stop();
      }
    };

    try {
      await new Promise<void>((res, rej) => {
        ws.onopen = () => res();
        ws.onerror = () => rej(new Error("WebSocket connection failed — is the backend running?"));
      });
    } catch (e: unknown) {
      setStatus((e as Error).message);
      return;
    }

    if (sttBackend === "openai_realtime") {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext({ sampleRate: 24000 });
      ctxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const processor = ctx.createScriptProcessor(2048, 1, 1);
      pcmRef.current = processor;
      processor.onaudioprocess = (e) => {
        if (ws.readyState !== WebSocket.OPEN) return;
        const f32 = e.inputBuffer.getChannelData(0);
        const i16 = new Int16Array(f32.length);
        for (let i = 0; i < f32.length; i++) i16[i] = Math.max(-32768, Math.min(32767, Math.round(f32[i] * 32767)));
        let bin = "";
        new Uint8Array(i16.buffer).forEach((b) => { bin += String.fromCharCode(b); });
        ws.send(JSON.stringify({ type: "audio_chunk", data: btoa(bin), mime_type: "audio/pcm;rate=24000" }));
      };
      source.connect(processor);
      processor.connect(ctx.destination);
      setListening(true);
      setStatus("Listening via OpenAI Realtime…");
    } else {
      // Whisper — WebM + manual stop
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
      const recorder = new MediaRecorder(stream, { mimeType });
      mediaRef.current = recorder;
      const chunks: BlobPart[] = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
      recorder.onstop = async () => {
        if (!chunks.length) return;
        const buf = await new Blob(chunks, { type: mimeType }).arrayBuffer();
        let bin = "";
        new Uint8Array(buf).forEach((b) => { bin += String.fromCharCode(b); });
        ws.send(JSON.stringify({ type: "audio_chunk", data: btoa(bin), mime_type: mimeType }));
        ws.send(JSON.stringify({ type: "end_of_utterance" }));
        setStatus("Processing…");
      };
      recorder.start();
      setListening(true);
      setStatus("Listening via Whisper… (press Stop to transcribe)");
    }
  }, [sttBackend, stop]);

  return (
    <section className="panel stack" style={{ gap: 12 }}>
      <h3 style={{ margin: 0 }}>Speech-to-Text</h3>
      <p className="muted" style={{ margin: 0, fontSize: 13 }}>
        Provider: <strong>{sttBackend}</strong>
      </p>

      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" onClick={() => void (listening ? stop() : start())}>
          {listening ? "⏹ Stop" : "🎙 Start listening"}
        </button>
        {transcript && (
          <button
            type="button"
            className="secondary"
            onClick={() => { setTranscript(""); setInterim(""); }}
          >
            Clear
          </button>
        )}
      </div>

      {status && (
        <p style={{ margin: 0, fontSize: 13, color: status.startsWith("Error") ? "var(--error)" : "var(--text-secondary)" }}>
          {status}
        </p>
      )}

      <div style={{
        minHeight: 80, padding: "10px 12px",
        background: "var(--bg-base)", borderRadius: 6,
        border: "1px solid var(--border)", fontSize: 14, lineHeight: 1.6,
      }}>
        {transcript || interim
          ? <>
              {transcript}
              {interim && (
                <span style={{ color: "var(--text-secondary)" }}>
                  {transcript ? " " : ""}{interim}
                </span>
              )}
            </>
          : <span style={{ color: "var(--text-tertiary)" }}>Transcript will appear here…</span>
        }
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// TTS diagnostic — text input + play button, streams audio back
// ---------------------------------------------------------------------------

const DEFAULT_TTS_TEXT = "The quick brown fox jumps over the lazy dog. Testing one two three.";

function TTSDiagnostic() {
  const [text, setText] = useState(DEFAULT_TTS_TEXT);
  const [playing, setPlaying] = useState(false);
  const [status, setStatus] = useState("");
  const wsRef = useRef<WebSocket | null>(null);

  const ttsBackend = localStorage.getItem("voice_tts") ?? "elevenlabs";

  const play = useCallback(async () => {
    if (!text.trim() || playing) return;
    setPlaying(true);
    setStatus("Connecting…");

    const proto = location.protocol === "https:" ? "wss" : "ws";
    const stt = localStorage.getItem("voice_stt") ?? "openai";
    const ws = new WebSocket(`${proto}://${location.host}/api/voice/ws?stt=${stt}&tts=${ttsBackend}`);
    wsRef.current = ws;

    let done = false;
    const chunks: Uint8Array[] = [];

    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data as string) as { type: string; data?: string; message?: string };
      if (msg.type === "audio_chunk" && msg.data) {
        setStatus("Buffering…");
        const binary = atob(msg.data);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        chunks.push(bytes);
      } else if (msg.type === "audio_done") {
        done = true;
        ws.close();
        if (chunks.length) {
          const blob = new Blob(chunks, { type: "audio/mpeg" });
          const url = URL.createObjectURL(blob);
          const audio = new Audio(url);
          setStatus("Playing…");
          audio.onended = () => { URL.revokeObjectURL(url); setPlaying(false); setStatus("Done"); };
          audio.onerror = () => { URL.revokeObjectURL(url); setPlaying(false); setStatus("Playback error"); };
          void audio.play();
        } else {
          setPlaying(false);
          setStatus("Done (no audio received)");
        }
      } else if (msg.type === "error") {
        setStatus(`Error: ${msg.message ?? "unknown"}`);
        setPlaying(false);
        ws.close();
      }
    };

    ws.onerror = () => {
      setStatus("WebSocket error — is the backend running?");
      setPlaying(false);
    };

    ws.onopen = () => {
      setStatus("Synthesising…");
      ws.send(JSON.stringify({ type: "synthesize", text: text.trim() }));
    };

    setTimeout(() => {
      if (!done) { setPlaying(false); setStatus("Timed out"); ws.close(); }
    }, 30000);
  }, [text, playing, ttsBackend]);

  return (
    <section className="panel stack" style={{ gap: 12 }}>
      <h3 style={{ margin: 0 }}>Text-to-Speech</h3>
      <p className="muted" style={{ margin: 0, fontSize: 13 }}>
        Provider: <strong>{ttsBackend}</strong>
      </p>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        style={{
          resize: "vertical", fontFamily: "inherit", fontSize: 14,
          background: "var(--bg-elevated)", color: "var(--text-primary)",
          border: "1px solid var(--border-strong)", borderRadius: 6,
          padding: "8px 10px", lineHeight: 1.5, width: "100%",
          boxSizing: "border-box",
        }}
      />

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button type="button" onClick={() => void play()} disabled={playing || !text.trim()}>
          {playing ? "⏳ Playing…" : "▶ Play"}
        </button>
        {status && (
          <span style={{ fontSize: 13, color: status.startsWith("Error") ? "var(--error)" : "var(--text-secondary)" }}>
            {status}
          </span>
        )}
      </div>
    </section>
  );
}
