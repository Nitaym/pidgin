import { useCallback, useRef, useState } from "react";
import type { HireCustomization } from "../types/hire";
import type { AgentGender } from "../utils/agentNameGenerator";
import { presetsForGender, resolveAgentVoice } from "../utils/voicePresets";

type BriefFormProps = {
  value: HireCustomization;
  onChange: (next: HireCustomization) => void;
  showYourTake?: boolean;
};

const PREVIEW_TEXT = "Hi, I'm your new teammate. Looking forward to working together!";

/** Plays a short TTS sample for the given voice preset. */
function useVoicePreview() {
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState("");
  const wsRef = useRef<WebSocket | null>(null);

  const preview = useCallback((voicePreset: string) => {
    if (previewing) return;
    setPreviewing(true);
    setError("");

    const proto = location.protocol === "https:" ? "wss" : "ws";
    const tts = localStorage.getItem("voice_tts") ?? "elevenlabs";
    const ws = new WebSocket(
      `${proto}://${location.host}/api/voice/ws?tts=${tts}&voice=${encodeURIComponent(voicePreset)}`,
    );
    wsRef.current = ws;
    const chunks: Uint8Array[] = [];
    let done = false;

    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data as string) as { type: string; data?: string; message?: string };
      if (msg.type === "audio_chunk" && msg.data) {
        const binary = atob(msg.data);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        chunks.push(bytes);
      } else if (msg.type === "audio_done") {
        done = true;
        ws.close();
        if (chunks.length) {
          const url = URL.createObjectURL(new Blob(chunks, { type: "audio/mpeg" }));
          const audio = new Audio(url);
          audio.onended = () => { URL.revokeObjectURL(url); setPreviewing(false); };
          audio.onerror = () => { URL.revokeObjectURL(url); setPreviewing(false); };
          void audio.play();
        } else {
          setPreviewing(false);
        }
      } else if (msg.type === "error") {
        setError(msg.message ?? "Preview failed");
        setPreviewing(false);
        ws.close();
      }
    };
    ws.onerror = () => { setError("Preview failed — is the backend running?"); setPreviewing(false); };
    ws.onopen = () => ws.send(JSON.stringify({ type: "synthesize", text: PREVIEW_TEXT }));
    setTimeout(() => { if (!done) { setPreviewing(false); ws.close(); } }, 20000);
  }, [previewing]);

  return { preview, previewing, error };
}

function linesToList(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function listToLines(items: string[]): string {
  return items.join("\n");
}

export function BriefForm({ value, onChange, showYourTake = true }: BriefFormProps) {
  const job = value.job_requirements;
  const ideal = value.ideal_candidate;
  const gender = (value.gender ?? "") as AgentGender;
  const voice = value.voice ?? "";
  const { preview, previewing, error: previewError } = useVoicePreview();

  function handleGenderChange(nextGender: AgentGender) {
    // Reset the voice if it no longer fits the new gender
    const stillValid =
      !voice || presetsForGender(nextGender).some((p) => p.key === voice);
    onChange({ ...value, gender: nextGender, voice: stillValid ? voice : "" });
  }

  return (
    <div className="brief-form stack">
      <section className="brief-section">
        <h3 className="brief-section-title">Voice &amp; persona</h3>
        <div className="field">
          <label htmlFor="brief-gender">Gender</label>
          <select
            id="brief-gender"
            value={gender}
            onChange={(e) => handleGenderChange(e.target.value as AgentGender)}
          >
            <option value="">Unspecified</option>
            <option value="female">Female</option>
            <option value="male">Male</option>
          </select>
          <p className="field-hint">Used to suggest a fitting name and default voice.</p>
        </div>
        <div className="field">
          <label htmlFor="brief-voice">Voice</label>
          <div className="field-inline">
            <select
              id="brief-voice"
              value={voice}
              onChange={(e) => onChange({ ...value, voice: e.target.value })}
            >
              <option value="">Auto (match gender)</option>
              {presetsForGender(gender).map((p) => (
                <option key={p.key} value={p.key}>{p.label}</option>
              ))}
            </select>
            <button
              type="button"
              className="secondary"
              disabled={previewing}
              onClick={() => preview(resolveAgentVoice(voice, gender))}
            >
              {previewing ? "⏳ Playing…" : "▶ Preview"}
            </button>
          </div>
          {previewError ? (
            <p className="field-hint" style={{ color: "var(--error)" }}>{previewError}</p>
          ) : null}
        </div>
      </section>

      <section className="brief-section">
        <h3 className="brief-section-title">Job requirements</h3>
        <div className="field">
          <label htmlFor="brief-mission">Mission</label>
          <textarea
            id="brief-mission"
            rows={5}
            value={job.mission}
            onChange={(e) =>
              onChange({
                ...value,
                job_requirements: { ...job, mission: e.target.value },
              })
            }
          />
        </div>
        <div className="field">
          <label htmlFor="brief-responsibilities">Responsibilities (one per line)</label>
          <textarea
            id="brief-responsibilities"
            rows={6}
            value={listToLines(job.responsibilities)}
            onChange={(e) =>
              onChange({
                ...value,
                job_requirements: {
                  ...job,
                  responsibilities: linesToList(e.target.value),
                },
              })
            }
          />
        </div>
        <div className="field">
          <label htmlFor="brief-out-of-scope">Out of scope (one per line)</label>
          <textarea
            id="brief-out-of-scope"
            rows={5}
            value={listToLines(job.out_of_scope)}
            onChange={(e) =>
              onChange({
                ...value,
                job_requirements: {
                  ...job,
                  out_of_scope: linesToList(e.target.value),
                },
              })
            }
          />
        </div>
      </section>

      <section className="brief-section">
        <h3 className="brief-section-title">Ideal candidate profile</h3>
        <div className="field">
          <label htmlFor="brief-tone">Tone</label>
          <textarea
            id="brief-tone"
            rows={4}
            value={ideal.tone}
            onChange={(e) =>
              onChange({
                ...value,
                ideal_candidate: { ...ideal, tone: e.target.value },
              })
            }
          />
        </div>
        <div className="field">
          <label htmlFor="brief-decision-framework">Decision framework</label>
          <textarea
            id="brief-decision-framework"
            rows={5}
            value={ideal.decision_framework}
            onChange={(e) =>
              onChange({
                ...value,
                ideal_candidate: { ...ideal, decision_framework: e.target.value },
              })
            }
          />
        </div>
        <div className="field">
          <label htmlFor="brief-escalation-rules">Escalation rules</label>
          <textarea
            id="brief-escalation-rules"
            rows={5}
            value={ideal.escalation_rules}
            onChange={(e) =>
              onChange({
                ...value,
                ideal_candidate: { ...ideal, escalation_rules: e.target.value },
              })
            }
          />
        </div>
      </section>

      {showYourTake ? (
        <section className="brief-section">
          <h3 className="brief-section-title">Your take</h3>
          <div className="field">
            <label htmlFor="brief-your-take">Notes for this hire</label>
            <textarea
              id="brief-your-take"
              rows={6}
              placeholder="Anything specific to this role or candidate…"
              value={value.your_take}
              onChange={(e) => onChange({ ...value, your_take: e.target.value })}
            />
          </div>
        </section>
      ) : null}
    </div>
  );
}
