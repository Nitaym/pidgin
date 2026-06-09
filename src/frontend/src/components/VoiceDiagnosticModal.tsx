import { useCallback, useEffect, useRef, useState } from "react";

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
          Tests your configured STT and TTS providers in isolation. For full-loop pipeline timing
          and LLM input/output, open a chat and toggle <strong>📊 Diagnostics</strong> in the chat header.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <STTDiagnostic />
          <TTSDiagnostic />
        </div>
      </div>
    </div>
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
