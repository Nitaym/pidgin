import { useState } from "react";
import { VoiceDiagnosticModal } from "../components/VoiceDiagnosticModal";

const STT_OPTIONS = [
  { value: "openai", label: "OpenAI Whisper" },
  { value: "web_speech", label: "Browser (Web Speech API)" },
  { value: "openai_realtime", label: "OpenAI Realtime" },
  { value: "elevenlabs", label: "ElevenLabs (coming soon)", disabled: true },
] as const;

const TTS_OPTIONS = [
  { value: "elevenlabs", label: "ElevenLabs" },
  { value: "openai", label: "OpenAI TTS" },
] as const;

export function SettingsPage() {
  const [stt, setStt] = useState(() => localStorage.getItem("voice_stt") ?? "openai");
  const [tts, setTts] = useState(() => localStorage.getItem("voice_tts") ?? "elevenlabs");
  const [saved, setSaved] = useState(false);
  const [diagOpen, setDiagOpen] = useState(false);

  function handleSave() {
    localStorage.setItem("voice_stt", stt);
    localStorage.setItem("voice_tts", tts);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <p className="eyebrow" style={{ margin: "0 0 4px" }}>System</p>
          <h2>Settings</h2>
        </div>
      </div>

      <section className="brief-section">
        <h3 className="brief-section-title">Voice</h3>
        <div className="panel stack" style={{ padding: "20px 24px", gap: 20 }}>

          <div className="field">
            <label htmlFor="stt-select">Speech-to-Text</label>
            <select
              id="stt-select"
              value={stt}
              onChange={(e) => setStt(e.target.value)}
            >
              {STT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value} disabled={"disabled" in o && o.disabled}>
                  {o.label}
                </option>
              ))}
            </select>
            {stt === "web_speech" && (
              <p className="field-hint">
                Free, no API key needed. Chrome and Edge only.
              </p>
            )}
            {stt === "openai_realtime" && (
              <p className="field-hint">
                Requires OpenAI Realtime API quota (Tier 3+).
              </p>
            )}
          </div>

          <div className="field">
            <label htmlFor="tts-select">Text-to-Speech</label>
            <select
              id="tts-select"
              value={tts}
              onChange={(e) => setTts(e.target.value)}
            >
              {TTS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <button type="button" onClick={handleSave}>
              Save
            </button>
            <button type="button" className="secondary" onClick={() => setDiagOpen(true)}>
              🎙 Test voice settings
            </button>
            {saved && (
              <span style={{ fontSize: 13, color: "var(--success)" }}>Saved ✓</span>
            )}
          </div>
        </div>
      </section>

      <VoiceDiagnosticModal open={diagOpen} onClose={() => setDiagOpen(false)} />
    </div>
  );
}
