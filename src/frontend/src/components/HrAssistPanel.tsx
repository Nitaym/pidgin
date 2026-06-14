import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { HireCustomization, HrAssistMessage } from "../types/hire";

type HrAssistPanelProps = {
  slug: string;
  contextType: "hire" | "agent" | "template";
  contextId: string;
  customization: HireCustomization;
  onApplyCustomization: (next: HireCustomization) => void;
};

function applySuggestion(
  customization: HireCustomization,
  suggestion: HrAssistMessage["suggestion"],
): HireCustomization {
  if (!suggestion) return customization;
  const next = structuredClone(customization);
  if (suggestion.action === "append_your_take") {
    const addition = suggestion.targets.your_take ?? "";
    next.your_take = next.your_take ? `${next.your_take}\n${addition}` : addition;
    return next;
  }
  for (const [path, text] of Object.entries(suggestion.targets)) {
    if (path === "job_requirements.mission") next.job_requirements.mission = text;
    if (path === "ideal_candidate.tone") next.ideal_candidate.tone = text;
    if (path === "ideal_candidate.decision_framework") {
      next.ideal_candidate.decision_framework = text;
    }
    if (path === "ideal_candidate.escalation_rules") {
      next.ideal_candidate.escalation_rules = text;
    }
  }
  return next;
}

export function HrAssistPanel({
  slug,
  contextType,
  contextId,
  customization,
  onApplyCustomization,
}: HrAssistPanelProps) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<HrAssistMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void api
      .createHrAssistSession(slug, contextType, contextId)
      .then((session) => {
        if (!cancelled) {
          setSessionId(session.session_id);
          setMessages(session.messages ?? []);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [slug, contextType, contextId]);

  async function handleSend(event: React.FormEvent) {
    event.preventDefault();
    if (!sessionId || !draft.trim()) return;
    setSending(true);
    setError(null);
    try {
      const result = await api.sendHrAssistMessage(
        slug,
        sessionId,
        draft.trim(),
        customization,
      );
      setMessages((prev) => [
        ...prev,
        result.operator_message as HrAssistMessage,
        result.assist_message as HrAssistMessage,
      ]);
      setDraft("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Assist unavailable");
    } finally {
      setSending(false);
    }
  }

  const lastAssist = [...messages].reverse().find((m) => m.role === "assist");

  return (
    <aside className="hr-assist panel stack">
      <h4 style={{ margin: 0 }}>Discuss with Pidgin</h4>
      <p className="muted" style={{ margin: 0, fontSize: "0.9rem" }}>
        Hiring coach — helps tighten job requirements and ideal candidate wording.
      </p>
      {error ? <div className="error">{error}</div> : null}
      <div className="hr-assist-messages">
        {messages.length === 0 ? (
          <p className="muted">Ask for help with mission, tone, or your take.</p>
        ) : (
          messages.map((msg) => (
            <div key={msg.id} className={`hr-msg ${msg.role}`}>
              <div className="meta">{msg.role === "operator" ? "You" : "Pidgin"}</div>
              <div>{msg.body_text}</div>
            </div>
          ))
        )}
      </div>
      {lastAssist?.suggestion ? (
        <div className="stack">
          <button
            type="button"
            className="secondary"
            onClick={() =>
              onApplyCustomization(applySuggestion(customization, lastAssist.suggestion))
            }
          >
            {lastAssist.suggestion.action === "append_your_take"
              ? "Append to your take"
              : "Apply to form"}
          </button>
        </div>
      ) : null}
      <form className="row" onSubmit={(e) => void handleSend(e)}>
        <input
          style={{ flex: 1 }}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask Pidgin…"
          disabled={!sessionId || sending}
        />
        <button type="submit" disabled={!sessionId || sending || !draft.trim()}>
          Send
        </button>
      </form>
    </aside>
  );
}
