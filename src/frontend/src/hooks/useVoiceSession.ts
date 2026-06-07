import { useCallback, useEffect, useRef, useState } from "react";

export type VoiceState = "idle" | "recording" | "processing" | "speaking" | "error";

export interface VoiceSessionOptions {
  onTranscript: (text: string) => void;
  onTranscriptDelta?: (delta: string) => void;
  onAudioDone?: () => void;
  onError?: (message: string) => void;
  micDeviceId?: string;
  speakerDeviceId?: string;
  /** ms of silence before auto-submitting — Whisper mode only */
  silenceMs?: number;
}

export function useVoiceSession(options: VoiceSessionOptions) {
  const {
    onTranscript, onTranscriptDelta, onAudioDone, onError,
    micDeviceId, speakerDeviceId, silenceMs = 700,
  } = options;

  const [state, setState] = useState<VoiceState>("idle");
  const wsRef = useRef<WebSocket | null>(null);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const pcmRef = useRef<ScriptProcessorNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const vadRef = useRef<ReturnType<typeof startVAD> | null>(null);
  const srRef = useRef<SpeechRecognition | null>(null);
  const speakerIdRef = useRef(speakerDeviceId);
  useEffect(() => { speakerIdRef.current = speakerDeviceId; }, [speakerDeviceId]);

  const onTranscriptRef = useRef(onTranscript);
  const onTranscriptDeltaRef = useRef(onTranscriptDelta);
  const onErrorRef = useRef(onError);
  const onAudioDoneRef = useRef(onAudioDone);
  useEffect(() => { onTranscriptRef.current = onTranscript; }, [onTranscript]);
  useEffect(() => { onTranscriptDeltaRef.current = onTranscriptDelta; }, [onTranscriptDelta]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);
  useEffect(() => { onAudioDoneRef.current = onAudioDone; }, [onAudioDone]);

  const sttMode = () => localStorage.getItem("voice_stt") ?? "openai";
  const isRealtime = () => sttMode() === "openai_realtime";
  const isWebSpeech = () => sttMode() === "web_speech";

  // ---------------------------------------------------------------------------
  // Backend WS — single connection for both STT relay and TTS
  // ---------------------------------------------------------------------------

  const audioChunksRef = useRef<Uint8Array[]>([]);

  const handleMessage = useCallback((raw: string) => {
    const msg = JSON.parse(raw) as {
      type: string; text?: string; data?: string; message?: string;
    };
    if (msg.type === "transcript" && msg.text) {
      if (!isRealtime() && !isWebSpeech()) setState("idle");
      onTranscriptRef.current(msg.text);
    } else if (msg.type === "transcript_delta" && msg.text) {
      onTranscriptDeltaRef.current?.(msg.text);
    } else if (msg.type === "audio_chunk" && msg.data) {
      // Buffer chunks — partial MP3 fragments don't play cleanly on their own
      const binary = atob(msg.data);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      audioChunksRef.current.push(bytes);
      setState("speaking");
    } else if (msg.type === "audio_done") {
      // Play the complete buffered audio
      if (audioChunksRef.current.length > 0) {
        const blob = new Blob(audioChunksRef.current, { type: "audio/mpeg" });
        audioChunksRef.current = [];
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        if (speakerIdRef.current && speakerIdRef.current !== "default" && "setSinkId" in audio) {
          (audio as HTMLAudioElement & { setSinkId: (id: string) => Promise<void> })
            .setSinkId(speakerIdRef.current).catch(() => {});
        }
        audio.onended = () => URL.revokeObjectURL(url);
        void audio.play();
      }
      audioChunksRef.current = [];
      setState(isRealtime() || isWebSpeech() ? "recording" : "idle");
      onAudioDoneRef.current?.();
    } else if (msg.type === "error") {
      setState("error");
      onErrorRef.current?.(msg.message ?? "Unknown voice error");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const connect = useCallback((): Promise<WebSocket> => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return Promise.resolve(wsRef.current);
    return new Promise((resolve, reject) => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const stt = localStorage.getItem("voice_stt") ?? "openai";
      const tts = localStorage.getItem("voice_tts") ?? "elevenlabs";
      const ws = new WebSocket(`${proto}://${location.host}/api/voice/ws?stt=${stt}&tts=${tts}`);
      ws.onopen = () => { wsRef.current = ws; resolve(ws); };
      ws.onerror = () => reject(new Error("WebSocket connection failed — is the backend running?"));
      ws.onmessage = (ev) => handleMessage(ev.data as string);
      ws.onclose = () => { wsRef.current = null; };
    });
  }, [handleMessage]);

  // ---------------------------------------------------------------------------
  // Recording helpers
  // ---------------------------------------------------------------------------

  const stopPcmCapture = useCallback(() => {
    pcmRef.current?.disconnect();
    pcmRef.current = null;
    if (audioCtxRef.current) {
      void audioCtxRef.current.close();
      audioCtxRef.current = null;
    }
  }, []);

  const sendEndOfUtterance = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: "end_of_utterance" }));
    vadRef.current?.stop();
    vadRef.current = null;
    setState("processing");
  }, []);

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  const startRecording = useCallback(async () => {
    try {
      const ws = await connect();

      if (isWebSpeech()) {
        // Web Speech API — browser-native STT, no audio sent to backend
        const SR = window.SpeechRecognition ?? (window as unknown as { webkitSpeechRecognition: typeof SpeechRecognition }).webkitSpeechRecognition;
        if (!SR) {
          throw new Error("Web Speech API not supported in this browser. Use Chrome or Edge.");
        }
        const sr = new SR();
        srRef.current = sr;
        sr.continuous = true;
        sr.interimResults = true;
        sr.lang = "en-US";

        sr.onresult = (e: SpeechRecognitionEvent) => {
          let interim = "";
          for (let i = e.resultIndex; i < e.results.length; i++) {
            const result = e.results[i];
            if (result.isFinal) {
              const text = result[0].transcript.trim();
              if (text) onTranscriptRef.current(text);
            } else {
              interim += result[0].transcript;
            }
          }
          if (interim) onTranscriptDeltaRef.current?.(interim);
        };

        sr.onerror = (e: SpeechRecognitionErrorEvent) => {
          if (e.error === "no-speech") return; // ignore silence
          setState("error");
          onErrorRef.current?.(`Speech recognition error: ${e.error}`);
        };

        sr.onend = () => {
          // Auto-restart if still supposed to be recording
          if (srRef.current === sr && state === "recording") sr.start();
        };

        sr.start();
        setState("recording");
        return;
      }

      const realtimeMode = isRealtime();
      const constraints: MediaStreamConstraints = {
        audio: micDeviceId && micDeviceId !== "default"
          ? { deviceId: { exact: micDeviceId } }
          : true,
      };
      const stream = await navigator.mediaDevices.getUserMedia(constraints);

      if (realtimeMode) {
        // PCM16 @ 24kHz — backend relays to gpt-realtime-whisper, server VAD handles turns
        const ctx = new AudioContext({ sampleRate: 24000 });
        audioCtxRef.current = ctx;
        const source = ctx.createMediaStreamSource(stream);
        const processor = ctx.createScriptProcessor(2048, 1, 1); // power-of-2, ~85ms
        pcmRef.current = processor;

        processor.onaudioprocess = (e) => {
          if (ws.readyState !== WebSocket.OPEN) return;
          const int16 = float32ToInt16(e.inputBuffer.getChannelData(0));
          ws.send(JSON.stringify({
            type: "audio_chunk",
            data: arrayBufferToBase64(int16.buffer),
            mime_type: "audio/pcm;rate=24000",
          }));
        };

        source.connect(processor);
        processor.connect(ctx.destination); // required for onaudioprocess to fire
        setState("recording");

      } else {
        // WebM/Opus via MediaRecorder — client VAD → end_of_utterance → Whisper
        const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "audio/ogg";

        const recorder = new MediaRecorder(stream, { mimeType });
        mediaRef.current = recorder;

        recorder.ondataavailable = async (ev) => {
          if (ev.data.size === 0 || ws.readyState !== WebSocket.OPEN) return;
          const buf = await ev.data.arrayBuffer();
          ws.send(JSON.stringify({
            type: "audio_chunk",
            data: arrayBufferToBase64(buf),
            mime_type: mimeType,
          }));
        };

        recorder.start(100);
        setState("recording");

        vadRef.current = startVAD(stream, silenceMs, () => {
          if (mediaRef.current?.state === "recording") {
            mediaRef.current.stop();
            mediaRef.current.stream.getTracks().forEach((t) => t.stop());
            mediaRef.current = null;
            sendEndOfUtterance();
          }
        });
      }
    } catch (err) {
      setState("error");
      onErrorRef.current?.((err as Error).message);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connect, micDeviceId, silenceMs, sendEndOfUtterance, stopPcmCapture]);

  const stopRecording = useCallback(() => {
    vadRef.current?.stop();
    vadRef.current = null;

    if (srRef.current) {
      srRef.current.onend = null; // prevent auto-restart
      srRef.current.stop();
      srRef.current = null;
      setState("idle");
      return;
    }

    if (pcmRef.current) {
      stopPcmCapture();
      setState("idle");
      return;
    }

    const recorder = mediaRef.current;
    if (!recorder || recorder.state === "inactive") return;
    recorder.stop();
    recorder.stream.getTracks().forEach((t) => t.stop());
    mediaRef.current = null;
    sendEndOfUtterance();
  }, [sendEndOfUtterance, stopPcmCapture]);

  const synthesize = useCallback(async (text: string) => {
    try {
      const ws = await connect();
      ws.send(JSON.stringify({ type: "synthesize", text }));
      setState("speaking");
    } catch (err) {
      onErrorRef.current?.((err as Error).message);
    }
  }, [connect]);

  const disconnect = useCallback(() => {
    vadRef.current?.stop();
    vadRef.current = null;
    if (srRef.current) {
      srRef.current.onend = null;
      srRef.current.stop();
      srRef.current = null;
    }
    stopPcmCapture();
    wsRef.current?.close();
    wsRef.current = null;
    mediaRef.current?.stop();
    mediaRef.current = null;
    setState("idle");
  }, [stopPcmCapture]);

  useEffect(() => () => { disconnect(); }, [disconnect]);

  return { state, startRecording, stopRecording, synthesize, disconnect };
}

// ---------------------------------------------------------------------------
// VAD — silence detection (Whisper mode only)
// ---------------------------------------------------------------------------

interface VADHandle { stop: () => void }

function startVAD(stream: MediaStream, silenceMs: number, onSilence: () => void): VADHandle {
  const ctx = new AudioContext();
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  source.connect(analyser);

  const buf = new Uint8Array(analyser.frequencyBinCount);
  let silenceStart = 0;
  let triggered = false;
  let rafId = 0;
  const SILENCE_THRESHOLD = 8;

  function tick() {
    analyser.getByteFrequencyData(buf);
    const rms = buf.reduce((s, v) => s + v, 0) / buf.length;
    const now = Date.now();
    if (rms > SILENCE_THRESHOLD) {
      silenceStart = now;
    } else if (!triggered && now - silenceStart > silenceMs) {
      triggered = true;
      onSilence();
    }
    rafId = requestAnimationFrame(tick);
  }

  const timer = setTimeout(() => {
    silenceStart = Date.now();
    rafId = requestAnimationFrame(tick);
  }, 300);

  return {
    stop() {
      clearTimeout(timer);
      cancelAnimationFrame(rafId);
      source.disconnect();
      void ctx.close();
    },
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function float32ToInt16(samples: Float32Array): Int16Array {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    out[i] = Math.max(-32768, Math.min(32767, Math.round(samples[i] * 32767)));
  }
  return out;
}


function arrayBufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}
