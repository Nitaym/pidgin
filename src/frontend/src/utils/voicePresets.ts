/**
 * Voice presets — mirrors the backend catalog (src/pidgin/voice/catalog.py).
 * The preset key is what gets stored on the agent and sent on the voice
 * WebSocket as ?voice=<key>; the backend maps it to the provider voice.
 */

import type { AgentGender } from "./agentNameGenerator";

export interface VoicePreset {
  key: string;
  label: string;
  gender: AgentGender;
}

export const VOICE_PRESETS: VoicePreset[] = [
  { key: "female_warm", label: "Warm (female)", gender: "female" },
  { key: "female_bright", label: "Bright (female)", gender: "female" },
  { key: "male_deep", label: "Deep (male)", gender: "male" },
  { key: "male_casual", label: "Casual (male)", gender: "male" },
  { key: "neutral", label: "Neutral", gender: "" },
];

/** Presets compatible with the given gender ("" → all). */
export function presetsForGender(gender: AgentGender): VoicePreset[] {
  if (!gender) return VOICE_PRESETS;
  return VOICE_PRESETS.filter((p) => p.gender === gender || p.gender === "");
}

/** Concrete preset to use when the agent's voice is "" / "auto". */
export function defaultPresetForGender(gender: AgentGender): string {
  if (gender === "female") return "female_warm";
  if (gender === "male") return "male_deep";
  return "neutral";
}

/** Resolve an agent's stored voice ("" means auto) to a concrete preset key. */
export function resolveAgentVoice(voice: string | undefined, gender: AgentGender): string {
  return voice && voice !== "auto" ? voice : defaultPresetForGender(gender);
}
