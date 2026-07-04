import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { api, type Message } from "../api/client";
import { useWorkspaceEvent } from "../context/WorkspaceEvents";
import { useVoiceSession, type TimingMark } from "../hooks/useVoiceSession";
import { useAudioDevices } from "../hooks/useAudioDevices";
import { VoiceDiagnosticsPanel, type MarkMap, type LlmMarks } from "./VoiceDiagnosticsPanel";
import type { AgentGender } from "../utils/agentNameGenerator";
import { resolveAgentVoice } from "../utils/voicePresets";

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
  /** Hide the internal chat header — for embedding under an external header. */
  compact?: boolean;
};

export function ChatView({
  slug,
  agentHandle,
  agentDisplayName,
  backLink = { to: "..", label: "← Team" },
  inModal = false,
  compact = false,
}: ChatViewProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState<DraftMessage | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [voiceMode, setVoiceMode] = useState(false);
  const [resolvingApprovalId, setResolvingApprovalId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sendingRef = useRef(false); // synchronous guard against double-send

  // ── Diagnostics view ──
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [marks, setMarks] = useState<MarkMap>({});
  const [llm, setLlm] = useState<LlmMarks>({});
  const [diagTurnId, setDiagTurnId] = useState<string | undefined>(undefined);
  const [lastUserText, setLastUserText] = useState("");
  const onTimingMark = useCallback((m: TimingMark, t: number) => {
    // recordingStart begins a fresh turn — reset the marks/LLM timings.
    if (m === "recordingStart") { setMarks({ recordingStart: t }); setLlm({}); }
    else setMarks((prev) => ({ ...prev, [m]: t }));
  }, []);

  useEffect(() => {
    async function load() {
      if (!slug || !agentHandle) return;
      setError(null);
      try {
        const data = await api.getAgentMessages(slug, agentHandle);
        setMessages(data.messages);
        setConversationId(data.conversation_id);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load chat");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [slug, agentHandle]);

  // Live-append messages the agent posts into this thread while it's open —
  // e.g. an autonomous turn, or a reply landing after the stream closed. The
  // interactive send path refetches itself, so skip while it's active. A
  // resync (undefined payload, on SSE reconnect) also refetches.
  const onMessageEvent = useCallback(
    (payload: unknown) => {
      if (streaming || sendingRef.current || !slug || !agentHandle) return;
      const convId = (payload as { conversation_id?: string } | undefined)?.conversation_id;
      if (payload !== undefined && convId !== conversationId) return;
      api
        .getAgentMessages(slug, agentHandle)
        .then((fresh) => {
          setMessages(fresh.messages);
          setConversationId(fresh.conversation_id);
        })
        .catch(() => {});
    },
    [streaming, conversationId, slug, agentHandle],
  );
  useWorkspaceEvent("message.created", onMessageEvent);

  // The agent's configured voice (preset key), resolved from its brief.
  const [agentVoice, setAgentVoice] = useState<string | undefined>(undefined);
  useEffect(() => {
    if (!slug || !agentHandle) return;
    api.getAgentBrief(slug, agentHandle)
      .then((brief) => {
        const c = brief.customization;
        setAgentVoice(resolveAgentVoice(c?.voice, (c?.gender ?? "") as AgentGender));
      })
      .catch(() => setAgentVoice(undefined)); // fall back to provider default
  }, [slug, agentHandle]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, draft]);

  // Default focus to the composer whenever the chat is ready and not mid-voice-mode.
  useEffect(() => {
    if (!loading && !voiceMode) textareaRef.current?.focus();
  }, [loading, voiceMode, agentHandle]);

  function resizeTextarea() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }

  const sendMessage = useCallback(async (text: string) => {
    // sendingRef is synchronous — guards against two transcripts arriving
    // back-to-back before the `streaming` state has propagated.
    if (!text.trim() || !slug || sendingRef.current) return;
    sendingRef.current = true;
    setLastUserText(text);
    setLlm({ start: performance.now() });
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
            turn_id?: string;
          };
          if (parsed.type === "text_delta" && parsed.delta) {
            fullResponse += parsed.delta;
            setLlm((p) => (p.firstByte === undefined ? { ...p, firstByte: performance.now() } : p));
            // Pipeline TTS: speak each sentence as soon as it streams in,
            // rather than waiting for the full response.
            if (voiceMode) feedText(parsed.delta);
            setDraft((prev) =>
              prev ? { ...prev, text: prev.text + parsed.delta } : prev,
            );
          }
          if (parsed.type === "error") {
            source.close();
            sendingRef.current = false;
            setDraft(null);
            setStreaming(false);
            setError(parsed.message || "The agent encountered an error");
            return;
          }
          if (parsed.type === "invocation_end") {
            completed = true;
            source.close();
            sendingRef.current = false;
            setLlm((p) => ({ ...p, done: performance.now() }));
            if (parsed.turn_id) setDiagTurnId(parsed.turn_id);
            setDraft(null);
            void api.getAgentMessages(slug, agentHandle).then((fresh) => {
              setMessages(fresh.messages);
            });
            setStreaming(false);
            if (voiceMode) finishSpeaking(); // flush any trailing partial sentence
          }
        };
        source.onerror = () => {
          source.close();
          sendingRef.current = false;
          setDraft(null);
          setStreaming(false);
          if (!completed) {
            setError("Connection lost — check the server logs for details");
          }
        };
      } else if (data.messages) {
        sendingRef.current = false;
        setMessages(data.messages);
        setDraft(null);
        setStreaming(false);
      }
    } catch (err) {
      sendingRef.current = false;
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

  // Quick approve/reject right on the chat message that asked for it — the
  // Approvals page covers the same actions, but staying in the conversation
  // is faster for the common case of a single pending request.
  async function resolveInlineApproval(approvalId: string, decision: "approve" | "reject") {
    setResolvingApprovalId(approvalId);
    setError(null);
    try {
      if (decision === "approve") await api.approveApproval(slug, approvalId);
      else await api.rejectApproval(slug, approvalId);
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to ${decision}`);
    } finally {
      setResolvingApprovalId(null);
      // Refetch rather than patch locally — this also pulls in the outcome
      // notice the backend posts ("✅ Approved — …" / "❌ Not approved — …").
      try {
        const fresh = await api.getAgentMessages(slug, agentHandle);
        setMessages(fresh.messages);
      } catch {
        /* keep whatever is currently shown */
      }
    }
  }

  const [voiceError, setVoiceError] = useState<string | null>(null);
  const { mics, speakers, micId, setMicId, speakerId, setSpeakerId, refresh: refreshDevices } = useAudioDevices();
  const { state: voiceState, warming, warmup, startRecording, stopRecording, feedText, finishSpeaking, disconnect } = useVoiceSession({
    onTranscript: (text) => { void sendMessage(text); },
    onError: (msg) => setVoiceError(msg),
    onTimingMark,
    micDeviceId: micId,
    speakerDeviceId: speakerId,
    continuous: voiceMode, // hands-free: auto-resume listening after each agent reply
    voice: agentVoice,     // the agent's configured voice preset
  });
  const isRecording = voiceState === "recording";
  const voiceBusy = voiceState === "processing" || voiceState === "speaking";

  // Enter voice mode: warm the connection first, then start listening so the
  // user never pays connection/handshake latency in the hot path.
  const enterVoiceMode = useCallback(async () => {
    setVoiceMode(true);
    const ok = await warmup();
    if (ok) void startRecording();
  }, [warmup, startRecording]);

  const agentInitial = (agentDisplayName ?? agentHandle).charAt(0).toUpperCase();
  const displayName = agentDisplayName ?? `@${agentHandle}`;

  if (loading) {
    return <div className="chat-page"><p className="chat-loading">Loading…</p></div>;
  }

  const hasMessages = messages.length > 0 || draft !== null;

  return (
    <div className={`chat-page${inModal ? " chat-page--modal" : ""}`}>
      {!compact && (
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
          <button
            type="button"
            className="secondary"
            onClick={() => setShowDiagnostics((v) => !v)}
            aria-pressed={showDiagnostics}
            title="Toggle voice/LLM diagnostics"
            style={{ marginLeft: "auto", padding: "4px 12px", fontSize: 13 }}
          >
            {showDiagnostics ? "Hide diagnostics" : "📊 Diagnostics"}
          </button>
        </div>
      )}

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
                    {message.pending_approval_id && message.pending_approval_status === "open" ? (
                      <div className="chat-approval-actions">
                        <button
                          type="button"
                          className="btn"
                          disabled={resolvingApprovalId === message.pending_approval_id}
                          onClick={() => void resolveInlineApproval(message.pending_approval_id!, "approve")}
                        >
                          {resolvingApprovalId === message.pending_approval_id ? "Approving…" : "Approve"}
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          disabled={resolvingApprovalId === message.pending_approval_id}
                          onClick={() => void resolveInlineApproval(message.pending_approval_id!, "reject")}
                        >
                          Reject
                        </button>
                      </div>
                    ) : null}
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

      {showDiagnostics && (
        <div
          className="panel"
          style={{
            margin: "0 16px 12px", padding: "12px 16px", maxHeight: "40vh",
            overflow: "auto", borderRadius: 8,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <strong style={{ fontSize: 14 }}>Voice pipeline diagnostics</strong>
            <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
              {voiceState === "idle" ? "idle" : voiceState}
            </span>
          </div>
          <VoiceDiagnosticsPanel
            marks={marks}
            llm={llm}
            live={voiceState !== "idle" && voiceState !== "error"}
            slug={slug}
            turnId={diagTurnId}
            userText={lastUserText}
          />
        </div>
      )}

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
                disabled={voiceBusy || warming}
                aria-label={isRecording ? "Stop" : "Speak"}
                onClick={() => { if (isRecording) stopRecording(); else void startRecording(); }}
              >
                {warming ? <span className="spinner spinner--lg" /> : <MicIcon />}
              </button>
              <p className="voice-status">
                {voiceError
                  ? <span style={{ color: "#dc2626" }}>{voiceError}</span>
                  : warming ? "Warming up…" : isRecording ? "Listening…" : voiceState === "processing" ? "Transcribing…" : voiceState === "speaking" ? "Speaking…" : "Tap to speak"}
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
              onClick={() => { disconnect(); setVoiceMode(false); }}
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
              autoFocus
            />
            <div className="chat-compose-toolbar">
              <button
                type="button"
                className="chat-icon-btn"
                aria-label="Switch to voice"
                title="Voice conversation"
                onClick={() => { void enterVoiceMode(); }}
              >
                <MicIcon size={22} />
              </button>
              <button
                type="submit"
                className="chat-send-btn"
                disabled={streaming || !body.trim()}
                aria-label="Send"
              >
                <svg width="20" height="20" viewBox="0 0 16 16" fill="none">
                  <path d="M14 8L2 2l2.5 6L2 14l12-6z" fill="currentColor"/>
                </svg>
              </button>
            </div>
          </form>
        )}
        {!voiceMode && <p className="chat-footer-hint">Enter to send · Shift+Enter for new line</p>}
      </div>
    </div>
  );
}
