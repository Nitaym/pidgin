import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";

type ViewMode = "chat" | "raw";

type ChatMsg = { role: string; content: string; name?: string | null };
type ParsedAction = { action_type: string; params: Record<string, unknown> };
type ParsedResponse = {
  assistant_text?: string | null;
  actions?: ParsedAction[];
  stop_reason?: string | null;
  error_text?: string | null;
};

function parseJson<T>(raw: unknown, fallback: T): T {
  if (typeof raw !== "string" || !raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function roleTone(role: string): string {
  if (role === "assistant") return "#1f9d55";
  if (role === "system") return "#8a8a8a";
  if (role === "tool") return "#c07800";
  return "#1f6feb"; // user
}

function formatStamp(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function MessageBubble({
  role,
  label,
  content,
  time,
  title,
  collapsible = false,
}: {
  role: string;
  label: string;
  content: string;
  time?: string;
  title?: string;
  collapsible?: boolean;
}) {
  const isLong = content.length > 700;
  const [expanded, setExpanded] = useState(!collapsible || !isLong);
  const shown = expanded ? content : `${content.slice(0, 700)}…`;
  return (
    <div className="panel stack" style={{ gap: "0.35rem", borderLeft: `3px solid ${roleTone(role)}` }}>
      <div className="row" style={{ gap: "0.5rem", alignItems: "baseline", flexWrap: "wrap" }}>
        <span className="badge" style={{ background: roleTone(role), color: "#fff" }}>
          {label}
        </span>
        {title ? <strong>{title}</strong> : null}
        {time ? (
          <span className="muted" style={{ fontFamily: "monospace", fontSize: "0.78rem" }}>
            {formatStamp(time)}
          </span>
        ) : null}
        <span className="muted" style={{ fontSize: "0.78rem" }}>
          {content.length.toLocaleString()} chars
        </span>
        {isLong && collapsible ? (
          <button type="button" className="secondary" onClick={() => setExpanded((v) => !v)}>
            {expanded ? "Collapse" : "Expand"}
          </button>
        ) : null}
      </div>
      <pre className="llm-message-body" style={{ margin: 0, whiteSpace: "pre-wrap" }}>
        {shown}
      </pre>
    </div>
  );
}

type ChatEntry = {
  key: string;
  time: string;
  role: string;
  label: string;
  title?: string;
  content: string;
  collapsible?: boolean;
};

// Rebuild the turn as a timed conversation. Each invocation is one step with an
// `invoked_at`: its new input (the user message on the first call, tool results
// on later calls) and its response share that timestamp, so every message can
// show when it happened.
function buildEntries(invocations: Record<string, unknown>[]): ChatEntry[] {
  const sorted = [...invocations].sort(
    (a, b) => Number(a.sequence_in_turn) - Number(b.sequence_in_turn),
  );
  const entries: ChatEntry[] = [];
  sorted.forEach((inv, idx) => {
    const time = String(inv.invoked_at ?? "");
    const msgs = parseJson<ChatMsg[]>(inv.request_messages_json, []);
    if (idx === 0) {
      // First call carries the system prompt, prior history, and the user message.
      msgs.forEach((m, i) => {
        const isTool = m.role === "user" && m.content.startsWith("Tool results:");
        entries.push({
          key: `0-m${i}`,
          time,
          role: isTool ? "tool" : m.role,
          label: isTool ? "tool result" : m.role,
          content: m.content,
          collapsible: m.role === "system",
        });
      });
    } else {
      // Later calls only add the tool results fed back (the assistant message
      // between them is the previous response, already rendered).
      const tail = msgs[msgs.length - 1];
      if (tail) {
        const isTool = tail.role === "user" && tail.content.startsWith("Tool results:");
        entries.push({
          key: `${idx}-in`,
          time,
          role: isTool ? "tool" : tail.role,
          label: isTool ? "tool result" : tail.role,
          content: tail.content,
        });
      }
    }
    const resp = parseJson<ParsedResponse | null>(inv.response_json, null);
    if (resp?.assistant_text) {
      entries.push({
        key: `${idx}-out`,
        time,
        role: "assistant",
        label: "assistant",
        content: resp.assistant_text,
      });
    }
    (resp?.actions ?? []).forEach((action, i) => {
      entries.push({
        key: `${idx}-act${i}`,
        time,
        role: "assistant",
        label: "tool call",
        title: action.action_type,
        content: JSON.stringify(action.params, null, 2),
      });
    });
    if (resp?.error_text) {
      entries.push({
        key: `${idx}-err`,
        time,
        role: "assistant",
        label: "error",
        content: resp.error_text,
      });
    }
  });
  return entries;
}

function ChatView({
  invocations,
  triggeringEvent,
}: {
  invocations: Record<string, unknown>[];
  triggeringEvent: Record<string, unknown> | null;
}) {
  const [search, setSearch] = useState("");
  const [dir, setDir] = useState<"asc" | "desc">("asc");

  if (invocations.length === 0) {
    const payload = (triggeringEvent?.payload as Record<string, unknown>) ?? {};
    const text = String(payload.message_text ?? payload.message ?? "");
    return (
      <div className="stack">
        {text ? <MessageBubble role="user" label="user" content={text} /> : null}
        <p className="muted">No model calls in this turn.</p>
      </div>
    );
  }

  const entries = buildEntries(invocations);
  const query = search.trim().toLowerCase();
  const filtered = query
    ? entries.filter(
        (e) => e.content.toLowerCase().includes(query) || e.label.toLowerCase().includes(query),
      )
    : entries;
  // Entries are built oldest-first; sort by timestamp with a stable tiebreak so
  // steps sharing a timestamp keep their natural order.
  const ordered = filtered
    .map((e, i) => ({ e, i }))
    .sort((a, b) => {
      const cmp = a.e.time.localeCompare(b.e.time) || a.i - b.i;
      return dir === "asc" ? cmp : -cmp;
    })
    .map((x) => x.e);

  return (
    <div className="stack">
      <div className="row" style={{ gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <input
          type="search"
          placeholder="Search messages…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ flex: 1, minWidth: 180 }}
        />
        <button
          type="button"
          className="secondary"
          onClick={() => setDir((d) => (d === "asc" ? "desc" : "asc"))}
        >
          {dir === "asc" ? "Oldest first ↑" : "Newest first ↓"}
        </button>
        <span className="muted" style={{ fontSize: "0.8rem" }}>
          {ordered.length}/{entries.length}
        </span>
      </div>

      {ordered.length === 0 ? (
        <p className="muted">No messages match “{search}”.</p>
      ) : (
        ordered.map((e) => (
          <MessageBubble
            key={e.key}
            role={e.role}
            label={e.label}
            title={e.title}
            time={e.time}
            content={e.content}
            collapsible={e.collapsible}
          />
        ))
      )}
    </div>
  );
}

export function TurnDetailPage() {
  const { turnId = "" } = useParams();
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<ViewMode>("chat");

  useEffect(() => {
    async function load() {
      if (!slug || !turnId) return;
      setError(null);
      try {
        const data = await api.getTurn(slug, turnId);
        setDetail(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load turn");
      }
    }
    void load();
  }, [slug, turnId]);

  if (error) {
    return <div className="error">{error}</div>;
  }
  if (!detail) {
    return <p className="muted">Loading turn…</p>;
  }

  const invocations = (detail.model_invocations as Record<string, unknown>[]) ?? [];
  const audit = (detail.audit as Record<string, unknown>[]) ?? [];
  const triggeringEvent = (detail.triggering_event as Record<string, unknown>) ?? null;

  return (
    <div className="stack">
      <p className="muted">
        <Link to="../debug">← Debug</Link>
      </p>
      <h2>Turn {turnId}</h2>
      <section className="panel stack">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>Model invocations ({invocations.length})</h3>
          <div className="row" style={{ gap: "0.4rem" }}>
            {(["chat", "raw"] as ViewMode[]).map((m) => (
              <button
                key={m}
                type="button"
                className={mode === m ? "" : "secondary"}
                onClick={() => setMode(m)}
              >
                {m === "chat" ? "Chat" : "Raw"}
              </button>
            ))}
          </div>
        </div>
        {mode === "chat" ? (
          <ChatView invocations={invocations} triggeringEvent={triggeringEvent} />
        ) : invocations.length === 0 ? (
          <p className="muted">None</p>
        ) : (
          invocations.map((row) => (
            <pre key={String(row.id)} className="code-block">
              {JSON.stringify(row, null, 2)}
            </pre>
          ))
        )}
      </section>
      <section className="panel stack">
        <h3>Gate audit ({audit.length})</h3>
        {audit.length === 0 ? (
          <p className="muted">None</p>
        ) : (
          audit.map((row) => (
            <div key={String(row.id)} className="message">
              <div className="meta">
                {String(row.action_type)} · {String(row.outcome)} ·{" "}
                {String(row.policy_decision)}
              </div>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
