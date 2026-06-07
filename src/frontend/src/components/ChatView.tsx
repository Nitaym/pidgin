import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { api, type Message } from "../api/client";
import { useVoiceSession } from "../hooks/useVoiceSession";
import { useAudioDevices } from "../hooks/useAudioDevices";

function MicIcon({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 19v3M9 22h6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" />
    </svg>
  );
}

function SpeakerIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M11 5L6 9H2v6h4l5 4V5z" />
      <path d="M15.54 8.46a5 5 0 0 1 0 7.07M19.07 4.93a10 10 0 0 1 0 14.14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" />
    </svg>
  );
}

type DraftMessage = {
  text: string;
  status: "draft" | "final" | "cancelled";
};

type ChatViewProps = {
  slug: string;
  agentHandle: string;
  agentDisplayName?: string;
  backLink?: { to: string; label: string } | undefined;
  inModal?: boolean;
};

export function ChatView({
  slug,
  agentHandle,
  agentDisplayName,
  backLink = { to: "..", label: "← Team" },
  inModal = false,
}: ChatViewProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState<DraftMessage | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [voiceMode, setVoiceMode] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    async function load() {
      if (!slug || !agentHandle) return;
      setError(null);
      try {
        const data = await api.getAgentMessages(slug, agentHandle);
        setMessages(data.messages);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load chat");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [slug, agentHandle]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, draft]);

  function resizeTextarea() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || !slug || streaming) return;
    setError(null);
    setStreaming(true);
    setBody("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setMessages((prev) => [
      ...prev,
      {
        id: `optimistic-${Date.now()}`,
        body_text: text,
        sender_display_name: "You",
        created_at: new Date().toISOString(),
        originating_turn_id: null,
      },
    ]);
    setDraft({ text: "", status: "draft" });

    try {
      const data = await api.sendAgentMessage(slug, agentHandle, text, true);
      const streamPath =
        data.stream_url ?? `/${slug}/api/turns/stream/${data.event_id}`;
      if (streamPath) {
        let completed = false;
        let fullResponse = "";
        const source = new EventSource(streamPath);
        source.onmessage = (msg) => {
          const parsed = JSON.parse(msg.data) as {
            type: string;
            delta?: string;
            message?: string;
          };
          if (parsed.type === "text_delta" && parsed.delta) {
            fullResponse += parsed.delta;
            setDraft((prev) =>
              prev ? { ...prev, text: prev.text + parsed.delta } : prev,
            );
          }
          if (parsed.type === "error") {
            source.close();
            setDraft(null);
            setStreaming(false);
            setError(parsed.message || "The agent encountered an error");
            return;
          }
          if (parsed.type === "invocation_end") {
            completed = true;
            source.close();
            setDraft(null);
            void api.getAgentMessages(slug, agentHandle).then((fresh) => {
              setMessages(fresh.messages);
            });
            setStreaming(false);
            if (voiceMode && fullResponse) synthesize(fullResponse);
          }
        };
        source.onerror = () => {
          source.close();
          setDraft(null);
          setStreaming(false);
          if (!completed) {
            setError("Connection lost — check the server logs for details");
          }
        };
      } else if (data.messages) {
        setMessages(data.messages);
        setDraft(null);
        setStreaming(false);
      }
    } catch (err) {
      setDraft(null);
      setStreaming(false);
      setError(err instanceof Error ? err.message : "Send failed");
    }
  }, [slug, agentHandle, streaming, voiceMode]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleSend(event: React.FormEvent) {
    event.preventDefault();
    await sendMessage(body.trim());
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend(e as unknown as React.FormEvent);
    }
  }

  const [voiceError, setVoiceError] = useState<string | null>(null);
  const { mics, speakers, micId, setMicId, speakerId, setSpeakerId, refresh: refreshDevices } = useAudioDevices();
  const { state: voiceState, startRecording, stopRecording, synthesize } = useVoiceSession({
    onTranscript: (text) => { void sendMessage(text); },
    onError: (msg) => setVoiceError(msg),
    micDeviceId: micId,
    speakerDeviceId: speakerId,
  });
  const isRecording = voiceState === "recording";
  const voiceBusy = voiceState === "processing" || voiceState === "speaking";

  const agentInitial = (agentDisplayName ?? agentHandle).charAt(0).toUpperCase();
  const displayName = agentDisplayName ?? `@${agentHandle}`;

  if (loading) {
    return <div className="chat-page"><p className="chat-loading">Loading…</p></div>;
  }

  const hasMessages = messages.length > 0 || draft !== null;

  return (
    <div className={`chat-page${inModal ? " chat-page--modal" : ""}`}>
      <div className="chat-header">
        {!inModal && backLink && (
          <Link to={backLink.to} className="chat-back-link">{backLink.label}</Link>
        )}
        <div className="chat-header-agent">
          <div className="chat-agent-avatar">{agentInitial}</div>
          <div>
            <div className="chat-agent-name">{displayName}</div>
            <div className="chat-agent-sub">Direct message</div>
          </div>
        </div>
      </div>

      <div className="chat-messages">
        {!hasMessages ? (
          <div className="chat-empty">
            <div className="chat-empty-avatar">{agentInitial}</div>
            <h3 className="chat-empty-title">Chat with {displayName}</h3>
            <p className="chat-empty-sub">Send a message to get started.</p>
          </div>
        ) : (
          <>
            {messages.map((message) => {
              const isHuman = message.originating_turn_id === null;
              return (
                <div key={message.id} className={`chat-message ${isHuman ? "chat-message--human" : "chat-message--agent"}`}>
                  {!isHuman && (
                    <div className="chat-message-avatar">{agentInitial}</div>
                  )}
                  <div className="chat-message-content">
                    <div className="chat-message-meta">{message.sender_display_name}</div>
                    <div className="chat-message-body">
                      {isHuman ? message.body_text : <ReactMarkdown>{message.body_text}</ReactMarkdown>}
                    </div>
                  </div>
                </div>
              );
            })}
            {draft ? (
              <div className="chat-message chat-message--agent">
                <div className="chat-message-avatar">{agentInitial}</div>
                <div className="chat-message-content">
                  <div className="chat-message-meta">
                    {displayName}
                    <span className="chat-typing-indicator">
                      <span className="chat-typing-dot" />
                      <span className="chat-typing-dot" />
                      <span className="chat-typing-dot" />
                    </span>
                  </div>
                  <div className="chat-message-body"><ReactMarkdown>{draft.text || "…"}</ReactMarkdown></div>
                </div>
              </div>
            ) : null}
          </>
        )}
        {error && <div className="chat-error">{error}</div>}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-footer">
        {voiceMode ? (
          <div className="voice-panel">
            <div className="voice-panel-main">
              <div className="voice-waveform" aria-hidden>
                {Array.from({ length: 28 }, (_, i) => (
                  <span key={i} className={`voice-bar${isRecording ? " voice-bar--active" : ""}`} style={{ animationDelay: `${(i * 37) % 600}ms` }} />
                ))}
              </div>
              <button
                type="button"
                className={`voice-mic-btn${isRecording ? " voice-mic-btn--recording" : ""}`}
                disabled={voiceBusy}
                aria-label={isRecording ? "Stop" : "Speak"}
                onClick={() => { if (isRecording) stopRecording(); else void startRecording(); }}
              >
                <MicIcon />
              </button>
              <p className="voice-status">
                {voiceError
                  ? <span style={{ color: "#dc2626" }}>{voiceError}</span>
                  : isRecording ? "Listening…" : voiceState === "processing" ? "Transcribing…" : voiceState === "speaking" ? "Speaking…" : "Tap to speak"}
              </p>
            </div>
            <div className="voice-devices">
              <label className="voice-device-label">
                <MicIcon />
                <select
                  className="voice-device-select"
                  value={micId}
                  onChange={(e) => setMicId(e.target.value)}
                  onFocus={() => void refreshDevices()}
                >
                  {mics.length === 0
                    ? <option value="default">Default microphone</option>
                    : mics.map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label}</option>)
                  }
                </select>
              </label>
              <label className="voice-device-label">
                <SpeakerIcon />
                <select
                  className="voice-device-select"
                  value={speakerId}
                  onChange={(e) => setSpeakerId(e.target.value)}
                  onFocus={() => void refreshDevices()}
                >
                  {speakers.length === 0
                    ? <option value="default">Default speaker</option>
                    : speakers.map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label}</option>)
                  }
                </select>
              </label>
            </div>
            <button
              type="button"
              className="voice-exit-btn"
              onClick={() => { stopRecording(); setVoiceMode(false); }}
              aria-label="Back to text"
            >
              ✕ text
            </button>
          </div>
        ) : (
          <form className="chat-compose" onSubmit={handleSend}>
            <textarea
              ref={textareaRef}
              className="chat-input"
              rows={1}
              value={body}
              onChange={(e) => { setBody(e.target.value); resizeTextarea(); }}
              onKeyDown={handleKeyDown}
              placeholder={`Message ${displayName}…`}
              disabled={streaming}
            />
            <button
              type="button"
              className="chat-voice-toggle"
              aria-label="Switch to voice"
              title="Voice conversation"
              onClick={() => { setVoiceMode(true); void startRecording(); }}
            >
              <MicIcon />
            </button>
            <button
              type="submit"
              className="chat-send-btn"
              disabled={streaming || !body.trim()}
              aria-label="Send"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M14 8L2 2l2.5 6L2 14l12-6z" fill="currentColor"/>
              </svg>
            </button>
          </form>
        )}
        {!voiceMode && <p className="chat-footer-hint">Enter to send · Shift+Enter for new line</p>}
      </div>
    </div>
  );
}
