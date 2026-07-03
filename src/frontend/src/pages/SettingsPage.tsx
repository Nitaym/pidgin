import { useEffect, useState } from "react";
import { VoiceDiagnosticModal } from "../components/VoiceDiagnosticModal";
import { api } from "../api/client";
import type { LlmModelOption } from "../api/client";
import { useApp } from "../context/AppContext";

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

function ModelSettings() {
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [models, setModels] = useState<LlmModelOption[]>([]);
  const [model, setModel] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    api
      .getLlmSettings(slug)
      .then((settings) => {
        setModels(settings.available_models);
        setModel(settings.default_model);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [slug]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const settings = await api.saveLlmSettings(slug, model);
      setModel(settings.default_model);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  const selected = models.find((m) => m.id === model);

  return (
    <section className="brief-section">
      <h3 className="brief-section-title">Model</h3>
      <div className="panel stack" style={{ padding: "20px 24px", gap: 20 }}>
        {loading ? (
          <p className="field-hint">Loading…</p>
        ) : (
          <>
            <div className="field">
              <label htmlFor="model-select">Default model for agent chat</label>
              <select
                id="model-select"
                value={model}
                onChange={(e) => setModel(e.target.value)}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label} — {m.tier}
                    {m.recommended ? " (recommended)" : ""}
                  </option>
                ))}
              </select>
              {selected && <p className="field-hint">{selected.description}</p>}
            </div>

            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <button type="button" onClick={handleSave} disabled={saving || !model}>
                Save
              </button>
              {saved && (
                <span style={{ fontSize: 13, color: "var(--success)" }}>Saved ✓</span>
              )}
              {error && (
                <span style={{ fontSize: 13, color: "var(--danger, #c33)" }}>{error}</span>
              )}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

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

      <ModelSettings />

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
