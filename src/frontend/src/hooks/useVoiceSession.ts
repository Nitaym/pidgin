import { useCallback, useEffect, useRef, useState } from "react";

export type VoiceState = "idle" | "recording" | "processing" | "speaking" | "error";

/** Timing marks emitted across a voice turn, all via performance.now() (ms). */
export type TimingMark =
  | "recordingStart"   // microphone capture started (timeline origin)
  | "speechEnd"        // end_of_utterance sent (user stopped speaking)
  | "transcript"       // final transcript received
  | "synthesizeStart"  // synthesize() called
  | "ttsFirstByte"     // first audio chunk received
  | "audioDone"        // all audio received
  | "playbackStart";   // browser actually started playing audio

export interface VoiceSessionOptions {
  onTranscript: (text: string) => void;
  onTranscriptDelta?: (delta: string) => void;
  onAudioDone?: () => void;
  onError?: (message: string) => void;
  /** Fires at each stage boundary so callers can measure latency. */
  onTimingMark?: (mark: TimingMark, t: number) => void;
  micDeviceId?: string;
  speakerDeviceId?: string;
  /** ms of silence before auto-submitting — Whisper mode only */
  silenceMs?: number;
  /** Hands-free conversation: auto-resume listening after the agent finishes speaking. */
  continuous?: boolean;
}

export function useVoiceSession(options: VoiceSessionOptions) {
  const {
    onTranscript, onTranscriptDelta, onAudioDone, onError, onTimingMark,
    micDeviceId, speakerDeviceId, silenceMs = 700, continuous = false,
  } = options;

  const [state, setState] = useState<VoiceState>("idle");
  const [ready, setReady] = useState(false);
  const [warming, setWarming] = useState(false);
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
  const onTimingMarkRef = useRef(onTimingMark);
  const continuousRef = useRef(continuous);
  useEffect(() => { onTranscriptRef.current = onTranscript; }, [onTranscript]);
  useEffect(() => { onTranscriptDeltaRef.current = onTranscriptDelta; }, [onTranscriptDelta]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);
  useEffect(() => { onAudioDoneRef.current = onAudioDone; }, [onAudioDone]);
  useEffect(() => { onTimingMarkRef.current = onTimingMark; }, [onTimingMark]);
  useEffect(() => { continuousRef.current = continuous; }, [continuous]);

  // Synchronous gate: exactly one transcript is accepted per recording session.
  // Blocks duplicate/echo transcripts and stray events while thinking/speaking.
  const acceptingTranscriptRef = useRef(false);
  // Set after startRecording defines it, so finalizeIfDone can auto-resume.
  const startRecordingRef = useRef<() => void>(() => {});

  const mark = useCallback((m: TimingMark) => {
    onTimingMarkRef.current?.(m, performance.now());
  }, []);

  const sttMode = () => localStorage.getItem("voice_stt") ?? "openai";
  const isRealtime = () => sttMode() === "openai_realtime";
  const isWebSpeech = () => sttMode() === "web_speech";

  // ---------------------------------------------------------------------------
  // TTS turn state — pipelined sentence streaming.
  //
  // A "speaking turn" can be fed text incrementally (feedText) while the LLM is
  // still generating. Each completed sentence is synthesized immediately, and
  // the resulting audio clips are played back-to-back via a queue so first
  // audio is heard long before the full response is ready.
  //
  // Timing marks are turn-level: synthesizeStart/ttsFirstByte fire on the FIRST
  // sentence (what the listener actually waits for); audioDone fires once every
  // sentence's audio has been received.
  // ---------------------------------------------------------------------------

  const ttsFirstByteSeenRef = useRef(false);     // first audio chunk of the turn
  const synthStartMarkedRef = useRef(false);     // synthesizeStart marked this turn
  const playbackStartMarkedRef = useRef(false);  // playbackStart marked this turn
  const turnActiveRef = useRef(false);
  const turnEndedRef = useRef(false);            // caller signalled: no more text
  const firstFlushedRef = useRef(false);         // first clause of the turn sent
  const pendingSynthRef = useRef(0);             // synth requests awaiting audio_done
  const textBufRef = useRef("");                 // un-flushed transcript tail
  const sentenceChunksRef = useRef<Uint8Array[]>([]); // audio of the current sentence
  const playQueueRef = useRef<{ url: string; audio: HTMLAudioElement }[]>([]);
  const playingRef = useRef(false);

  // All audio received AND the caller has finished feeding text.
  const finalizeIfDone = useCallback(() => {
    if (!turnEndedRef.current || pendingSynthRef.current > 0) return;
    if (playingRef.current || playQueueRef.current.length > 0) return;
    // Nothing left to receive or play — the turn is complete.
    turnActiveRef.current = false;
    onAudioDoneRef.current?.();
    if (continuousRef.current) {
      // Hands-free: start listening again for the next turn.
      startRecordingRef.current();
    } else {
      setState("idle");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const playNext = useCallback(() => {
    if (playingRef.current) return;
    const next = playQueueRef.current.shift();
    if (!next) { finalizeIfDone(); return; }
    playingRef.current = true;
    if (!playbackStartMarkedRef.current) {
      playbackStartMarkedRef.current = true;
      next.audio.onplaying = () => mark("playbackStart");
    }
    next.audio.onended = () => {
      URL.revokeObjectURL(next.url);
      playingRef.current = false;
      playNext();
    };
    next.audio.onerror = () => {
      URL.revokeObjectURL(next.url);
      playingRef.current = false;
      playNext();
    };
    void next.audio.play();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mark, finalizeIfDone]);

  const enqueueAudio = useCallback((blob: Blob) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    if (speakerIdRef.current && speakerIdRef.current !== "default" && "setSinkId" in audio) {
      (audio as HTMLAudioElement & { setSinkId: (id: string) => Promise<void> })
        .setSinkId(speakerIdRef.current).catch(() => {});
    }
    playQueueRef.current.push({ url, audio });
    playNext();
  }, [playNext]);

  const handleMessage = useCallback((raw: string) => {
    const msg = JSON.parse(raw) as {
      type: string; text?: string; data?: string; message?: string;
    };
    if (msg.type === "transcript" && msg.text) {
      // One transcript per recording session — drop duplicates/echo.
      if (!acceptingTranscriptRef.current) return;
      acceptingTranscriptRef.current = false;
      mark("transcript");
      teardownCapture();       // silence the mic while the agent thinks + speaks
      setState("processing");
      onTranscriptRef.current(msg.text);
    } else if (msg.type === "transcript_delta" && msg.text) {
      onTranscriptDeltaRef.current?.(msg.text);
    } else if (msg.type === "audio_chunk" && msg.data) {
      // Buffer chunks per sentence — partial MP3 fragments don't decode alone
      if (!ttsFirstByteSeenRef.current) {
        ttsFirstByteSeenRef.current = true;
        mark("ttsFirstByte");
      }
      const binary = atob(msg.data);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      sentenceChunksRef.current.push(bytes);
      setState("speaking");
    } else if (msg.type === "audio_done") {
      // One sentence finished — enqueue its audio and play in order
      if (sentenceChunksRef.current.length > 0) {
        const blob = new Blob(sentenceChunksRef.current, { type: "audio/mpeg" });
        sentenceChunksRef.current = [];
        enqueueAudio(blob);
      }
      pendingSynthRef.current = Math.max(0, pendingSynthRef.current - 1);
      if (turnEndedRef.current && pendingSynthRef.current === 0) {
        mark("audioDone"); // all audio for the turn has now been received
      }
      finalizeIfDone();
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
      ws.onopen = () => { wsRef.current = ws; setReady(true); resolve(ws); };
      ws.onerror = () => reject(new Error("WebSocket connection failed — is the backend running?"));
      ws.onmessage = (ev) => handleMessage(ev.data as string);
      ws.onclose = () => { wsRef.current = null; setReady(false); };
    });
  }, [handleMessage]);

  // ---------------------------------------------------------------------------
  // Warmup — open the WS (and, for realtime, kick off the backend→OpenAI
  // handshake + TTS provider init) ahead of time so the listen path is instant.
  // ---------------------------------------------------------------------------

  const warmup = useCallback(async (): Promise<boolean> => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return true;
    setWarming(true);
    try {
      const ws = await connect();
      // Round-trip a ping so we know the backend is actually responsive,
      // not just that the socket opened.
      ws.send(JSON.stringify({ type: "ping" }));
      return true;
    } catch (err) {
      onErrorRef.current?.((err as Error).message);
      return false;
    } finally {
      setWarming(false);
    }
  }, [connect]);

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

  // Tear down all mic capture WITHOUT submitting an utterance. Used once a
  // transcript is in hand, so the mic is silent while the agent thinks/speaks
  // (prevents the agent's own audio from being re-transcribed as a new turn).
  const teardownCapture = useCallback(() => {
    vadRef.current?.stop();
    vadRef.current = null;
    if (srRef.current) {
      srRef.current.onend = null;
      srRef.current.onresult = null;
      try { srRef.current.stop(); } catch { /* ignore */ }
      srRef.current = null;
    }
    stopPcmCapture();
    if (mediaRef.current) {
      try {
        mediaRef.current.ondataavailable = null;
        if (mediaRef.current.state !== "inactive") mediaRef.current.stop();
        mediaRef.current.stream.getTracks().forEach((t) => t.stop());
      } catch { /* ignore */ }
      mediaRef.current = null;
    }
  }, [stopPcmCapture]);

  const sendEndOfUtterance = useCallback(() => {
    mark("speechEnd");
    wsRef.current?.send(JSON.stringify({ type: "end_of_utterance" }));
    vadRef.current?.stop();
    vadRef.current = null;
    setState("processing");
  }, [mark]);

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  const startRecording = useCallback(async () => {
    try {
      mark("recordingStart");
      acceptingTranscriptRef.current = true; // open the gate for this turn
      const ws = await connect();

      if (isWebSpeech()) {
        // Web Speech API — browser-native STT, no audio sent to backend
        const SR = window.SpeechRecognition ?? (window as unknown as { webkitSpeechRecognition: typeof SpeechRecognition }).webkitSpeechRecognition;
        if (!SR) {
          throw new Error("Web Speech API not supported in this browser. Use Chrome or Edge, or switch STT to OpenAI Whisper in Settings.");
        }
        // Web Speech only works in a secure context (HTTPS or localhost).
        // On a plain-http LAN address it fails with "not-allowed".
        if (!window.isSecureContext && !["localhost", "127.0.0.1"].includes(location.hostname)) {
          throw new Error(
            "Web Speech needs HTTPS or localhost — this page is served over an insecure connection. " +
            "Open the app via https://, or switch STT to OpenAI Whisper in Settings.",
          );
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
              if (text && acceptingTranscriptRef.current) {
                acceptingTranscriptRef.current = false;
                mark("transcript");
                teardownCapture();
                setState("processing");
                onTranscriptRef.current(text);
              }
            } else {
              interim += result[0].transcript;
            }
          }
          if (interim) onTranscriptDeltaRef.current?.(interim);
        };

        sr.onerror = (e: SpeechRecognitionErrorEvent) => {
          if (e.error === "no-speech" || e.error === "aborted") return; // benign
          // Permission/device errors are fatal — close the gate and drop the
          // recognizer so onend doesn't restart it in a loop.
          const fatal =
            e.error === "not-allowed" ||
            e.error === "service-not-allowed" ||
            e.error === "audio-capture";
          if (fatal) {
            acceptingTranscriptRef.current = false;
            srRef.current = null;
          }
          setState("error");
          onErrorRef.current?.(speechErrorMessage(e.error));
        };

        sr.onend = () => {
          // Browser ended recognition while we're still waiting for the user —
          // restart it (gate still open, no transcript accepted yet).
          if (srRef.current === sr && acceptingTranscriptRef.current) {
            try { sr.start(); } catch { /* already started */ }
          }
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
  }, [connect, micDeviceId, silenceMs, sendEndOfUtterance, stopPcmCapture, teardownCapture, mark]);

  useEffect(() => { startRecordingRef.current = () => { void startRecording(); }; }, [startRecording]);

  const stopRecording = useCallback(() => {
    acceptingTranscriptRef.current = false;
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

  // Stop any in-flight playback and drop the queue.
  const stopPlayback = useCallback(() => {
    for (const item of playQueueRef.current) {
      item.audio.onended = null;
      item.audio.onerror = null;
      try { item.audio.pause(); } catch { /* ignore */ }
      URL.revokeObjectURL(item.url);
    }
    playQueueRef.current = [];
    playingRef.current = false;
  }, []);

  // Begin a fresh speaking turn (reset all turn-level state).
  const beginTurn = useCallback(() => {
    stopPlayback();
    turnActiveRef.current = true;
    turnEndedRef.current = false;
    firstFlushedRef.current = false;
    synthStartMarkedRef.current = false;
    ttsFirstByteSeenRef.current = false;
    playbackStartMarkedRef.current = false;
    pendingSynthRef.current = 0;
    textBufRef.current = "";
    sentenceChunksRef.current = [];
  }, [stopPlayback]);

  // Send one sentence/segment to the backend for synthesis.
  const sendSynthesis = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    try {
      const ws = await connect();
      if (!synthStartMarkedRef.current) {
        synthStartMarkedRef.current = true;
        mark("synthesizeStart");
      }
      pendingSynthRef.current += 1;
      ws.send(JSON.stringify({ type: "synthesize", text: trimmed }));
      setState("speaking");
    } catch (err) {
      onErrorRef.current?.((err as Error).message);
    }
  }, [connect, mark]);

  // Feed streaming text (e.g. LLM deltas). Complete sentences are synthesized
  // as soon as they appear; the tail is buffered until more text arrives.
  const feedText = useCallback((delta: string) => {
    if (!turnActiveRef.current) beginTurn();
    textBufRef.current += delta;
    // For the very first segment of a turn, break on the first clause boundary
    // (comma/colon/semicolon as well as sentence enders) so first audio starts
    // as early as possible. After that, break on full sentences for natural
    // prosody. Newlines always break.
    for (;;) {
      const boundary = firstFlushedRef.current
        ? /[.!?](?=\s)|\n/
        : /[.!?,:;](?=\s)|\n/;
      const m = textBufRef.current.match(boundary);
      if (!m || m.index === undefined) break;
      const end = m.index + 1;
      const segment = textBufRef.current.slice(0, end);
      textBufRef.current = textBufRef.current.slice(end);
      firstFlushedRef.current = true; // synchronous, so the next loop uses sentences
      void sendSynthesis(segment);
    }
  }, [beginTurn, sendSynthesis]);

  // No more text is coming — flush the remaining tail and close out the turn.
  const finishSpeaking = useCallback(() => {
    if (!turnActiveRef.current) return;
    if (textBufRef.current.trim()) {
      void sendSynthesis(textBufRef.current);
    }
    textBufRef.current = "";
    turnEndedRef.current = true;
    finalizeIfDone(); // handles the "nothing to speak" case
  }, [sendSynthesis, finalizeIfDone]);

  // One-shot synthesis (e.g. a fixed string, no streaming).
  const synthesize = useCallback((text: string) => {
    beginTurn();
    void sendSynthesis(text);
    turnEndedRef.current = true;
  }, [beginTurn, sendSynthesis]);

  const disconnect = useCallback(() => {
    acceptingTranscriptRef.current = false;
    turnEndedRef.current = true; // prevent any pending finalize from auto-resuming
    vadRef.current?.stop();
    vadRef.current = null;
    if (srRef.current) {
      srRef.current.onend = null;
      srRef.current.stop();
      srRef.current = null;
    }
    stopPcmCapture();
    stopPlayback();
    turnActiveRef.current = false;
    wsRef.current?.close();
    wsRef.current = null;
    setReady(false);
    mediaRef.current?.stop();
    mediaRef.current = null;
    setState("idle");
  }, [stopPcmCapture, stopPlayback]);

  useEffect(() => () => { disconnect(); }, [disconnect]);

  return {
    state, ready, warming, warmup,
    startRecording, stopRecording,
    synthesize, feedText, finishSpeaking,
    disconnect,
  };
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

function speechErrorMessage(code: string): string {
  switch (code) {
    case "not-allowed":
    case "service-not-allowed":
      return "Microphone access for speech recognition was blocked. Allow the microphone in your " +
        "browser's site permissions and try again. (Web Speech also requires HTTPS or localhost — " +
        "if you're on a plain-http address, switch STT to OpenAI Whisper in Settings.)";
    case "audio-capture":
      return "No microphone was found. Check that an input device is connected and selected.";
    case "network":
      return "Speech recognition network error — the browser's speech service is unreachable.";
    default:
      return `Speech recognition error: ${code}`;
  }
}

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
