import { useEffect, useRef } from "react";
import { useVoiceSession, VoiceState } from "../hooks/useVoiceSession";

interface VoiceButtonProps {
  /** Called when the user finishes speaking; caller owns the agent turn. */
  onTranscript: (text: string) => void;
  /** Pass the agent response here to have it spoken aloud. */
  textToSpeak?: string;
  disabled?: boolean;
  className?: string;
}

export function VoiceButton({ onTranscript, textToSpeak, disabled, className }: VoiceButtonProps) {
  const { state, startRecording, stopRecording, synthesize } = useVoiceSession({
    onTranscript,
  });

  // When caller supplies new text to speak, synthesize it
  const prevText = usePrevious(textToSpeak);
  if (textToSpeak && textToSpeak !== prevText && state === "idle") {
    synthesize(textToSpeak);
  }

  const isRecording = state === "recording";
  const busy = state === "processing" || state === "speaking";

  const handleClick = () => {
    if (isRecording) stopRecording();
    else if (!busy) startRecording();
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled || busy}
      aria-label={label(state)}
      title={label(state)}
      className={[
        "voice-button",
        `voice-button--${state}`,
        className ?? "",
      ].join(" ")}
    >
      {icon(state)}
    </button>
  );
}

function label(s: VoiceState): string {
  if (s === "recording") return "Stop recording";
  if (s === "processing") return "Transcribing…";
  if (s === "speaking") return "Speaking…";
  if (s === "error") return "Voice error — click to retry";
  return "Start voice";
}

function icon(s: VoiceState): string {
  if (s === "recording") return "⏹";
  if (s === "processing") return "⏳";
  if (s === "speaking") return "🔊";
  return "🎙";
}

function usePrevious<T>(value: T): T | undefined {
  const ref = useRef<T | undefined>(undefined);
  useEffect(() => { ref.current = value; });
  return ref.current;
}
