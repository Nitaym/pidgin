import { useCallback, useEffect, useState } from "react";

export interface AudioDevice {
  deviceId: string;
  label: string;
}

export function useAudioDevices() {
  const [mics, setMics] = useState<AudioDevice[]>([]);
  const [speakers, setSpeakers] = useState<AudioDevice[]>([]);
  const [micId, setMicId] = useState<string>("default");
  const [speakerId, setSpeakerId] = useState<string>("default");

  const refresh = useCallback(async () => {
    // Permission must already be granted for labels to appear
    const devices = await navigator.mediaDevices.enumerateDevices();
    const inputs = devices
      .filter((d) => d.kind === "audioinput")
      .map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Microphone ${i + 1}` }));
    const outputs = devices
      .filter((d) => d.kind === "audiooutput")
      .map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Speaker ${i + 1}` }));
    setMics(inputs);
    setSpeakers(outputs);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  return { mics, speakers, micId, setMicId, speakerId, setSpeakerId, refresh };
}
