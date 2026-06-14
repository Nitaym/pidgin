import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { LlmChatMessage, LlmInvocation } from "../api/client";
import { useApp } from "../context/AppContext";

const POLL_MS = 2000;
const MAX_ROWS = 300;
const COLLAPSE_THRESHOLD = 700;

type DetailTab = "timeline" | "tools" | "raw";

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatCost(micros: number | null): string {
  if (micros == null) return "—";
  return `$${(micros / 1_000_000).toFixed(4)}`;
}

function shortModel(modelId: string): string {
  return modelId.replace(/-\d{8}$/, "");
}

function MessageCard({ message, index }: { message: LlmChatMessage; index: number }) {
  const isLong = message.content.length > COLLAPSE_THRESHOLD;
  const [expanded, setExpanded] = useState(!isLong || message.role !== "system");
  const shown =
    expanded || !isLong
      ? message.content
      : `${message.content.slice(0, COLLAPSE_THRESHOLD)}…`;
  // Tool results travel back to the model as user messages (see
  // turn_executor); surface them as what they really are.
  const isToolResult =
    message.role === "user" && message.content.startsWith("Tool results:");
  const badgeClass = isToolResult ? "tool" : message.role;
  const badgeLabel = isToolResult ? "tool result" : message.role;

  return (
    <div className={`llm-message llm-message-${badgeClass}`}>
      <div className="llm-message-head">
        <span className={`llm-role-badge llm-role-${badgeClass}`}>{badgeLabel}</span>
        <span className="muted">
          #{index}
          {message.name ? ` · ${message.name}` : ""}
          {message.tool_call_id ? ` · ${message.tool_call_id}` : ""}
          {` · ${message.content.length.toLocaleString()} chars`}
        </span>
        {isLong ? (
          <button
            type="button"
            className="llm-expand-btn"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "Collapse" : "Expand"}
          </button>
        ) : null}
      </div>
      <pre className="llm-message-body">{shown}</pre>
    </div>
  );
}

function InvocationDetail({ invocation, slug }: { invocation: LlmInvocation; slug: string }) {
  const [tab, setTab] = useState<DetailTab>("timeline");
  // Each LLM call re-sends the whole conversation, so consecutive calls look
  // near-identical. Default to a compact view: the system prompt plus the new
  // tail (what's actually new this call), with the repeated middle collapsed.
  const [fullContext, setFullContext] = useState(false);
  const response = invocation.response;

  const messages = invocation.request_messages;
  const hasSystem = messages[0]?.role === "system";
  const systemMsg = hasSystem ? messages[0] : null;
  const body = hasSystem ? messages.slice(1) : messages;
  const offset = hasSystem ? 1 : 0;
  // The last message is the new turn (user message or tool result); everything
  // before it is context carried over from earlier in the conversation.
  const tail = body.length > 0 ? body[body.length - 1] : null;
  const middle = body.slice(0, -1);

  return (
    <div className="llm-detail">
      <div className="llm-detail-meta">
        <span>
          <strong>req-{invocation.id.slice(-6).toLowerCase()}</strong>
        </span>
        <span>
          <strong>{invocation.agent_display_name ?? "unknown agent"}</strong>
          {invocation.agent_handle ? ` @${invocation.agent_handle}` : ""}
        </span>
        <span>{shortModel(invocation.model_id)}</span>
        <span>{invocation.provider}</span>
        <span>call #{invocation.sequence_in_turn}</span>
        <span>
          {invocation.input_tokens.toLocaleString()} in /{" "}
          {invocation.output_tokens.toLocaleString()} out
        </span>
        <span>{invocation.latency_ms != null ? `${invocation.latency_ms} ms` : "—"}</span>
        <span>{formatCost(invocation.cost_usd_micros)}</span>
        <Link to={`/${slug}/debug/turns/${invocation.turn_id}`}>
          turn {invocation.turn_id.slice(0, 8)}…
        </Link>
      </div>

      {invocation.error_text ? (
        <div className="error">{invocation.error_text}</div>
      ) : null}

      <div className="llm-tabs">
        {(["timeline", "tools", "raw"] as DetailTab[]).map((name) => (
          <button
            key={name}
            type="button"
            className={tab === name ? "llm-tab active" : "llm-tab"}
            onClick={() => setTab(name)}
          >
            {name === "timeline"
              ? `Timeline (${invocation.request_messages.length})`
              : name === "tools"
                ? `Available tools (${invocation.request_tools.length})`
                : "Raw"}
          </button>
        ))}
      </div>

      {tab === "timeline" ? (
        <div className="stack">
          <div className="llm-timeline-divider">
            ▼ sent to {shortModel(invocation.model_id)}
            {middle.length > 0 ? (
              <button
                type="button"
                className="llm-expand-btn"
                onClick={() => setFullContext((v) => !v)}
              >
                {fullContext ? "Compact" : `Full context (${messages.length})`}
              </button>
            ) : null}
          </div>
          {fullContext ? (
            messages.map((message, i) => (
              <MessageCard key={`${invocation.id}-${i}`} message={message} index={i} />
            ))
          ) : (
            <>
              {systemMsg ? (
                <MessageCard
                  key={`${invocation.id}-sys`}
                  message={systemMsg}
                  index={0}
                />
              ) : null}
              {middle.length > 0 ? (
                <button
                  type="button"
                  className="llm-history-collapse"
                  onClick={() => setFullContext(true)}
                >
                  ▸ {middle.length} earlier message{middle.length > 1 ? "s" : ""} ·
                  repeated conversation context (click to expand)
                </button>
              ) : null}
              {tail ? (
                <MessageCard
                  key={`${invocation.id}-tail`}
                  message={tail}
                  index={offset + body.length - 1}
                />
              ) : null}
            </>
          )}
          <div className="llm-timeline-divider">
            ▲ model responded · stop_reason: {response?.stop_reason ?? "—"}
            {invocation.latency_ms != null ? ` · ${invocation.latency_ms} ms` : ""}
            {response?.error_text ? (
              <span className="llm-stop-error"> · {response.error_text}</span>
            ) : null}
          </div>
          {response?.assistant_text ? (
            <div className="llm-message llm-message-out">
              <div className="llm-message-head">
                <span className="llm-role-badge llm-role-assistant">assistant</span>
                <span className="muted">says</span>
              </div>
              <pre className="llm-message-body">{response.assistant_text}</pre>
            </div>
          ) : null}
          {(response?.actions ?? []).map((action, i) => (
            <div key={`${invocation.id}-action-${i}`} className="llm-message llm-message-out">
              <div className="llm-message-head">
                <span className="llm-role-badge llm-role-tool">tool call</span>
                <strong className="llm-tool-name">{action.action_type}</strong>
                <span className="muted">— model wants this run before it can finish</span>
              </div>
              <pre className="llm-message-body">
                {JSON.stringify(action.params, null, 2)}
              </pre>
            </div>
          ))}
          {!response?.assistant_text && (response?.actions ?? []).length === 0 ? (
            <p className="muted">Model produced no text and no tool calls.</p>
          ) : null}
        </div>
      ) : null}

      {tab === "tools" ? (
        <div className="stack">
          {invocation.request_tools.length === 0 ? (
            <p className="muted">No tools offered to the model.</p>
          ) : (
            invocation.request_tools.map((tool) => (
              <div key={tool.name} className="llm-message">
                <div className="llm-message-head">
                  <span className="llm-role-badge llm-role-tool">{tool.name}</span>
                  <span className="muted">{tool.description}</span>
                </div>
                <pre className="llm-message-body">
                  {JSON.stringify(tool.parameters, null, 2)}
                </pre>
              </div>
            ))
          )}
        </div>
      ) : null}

      {tab === "raw" ? (
        <pre className="llm-message-body llm-raw">
          {JSON.stringify(invocation, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

export function LlmInspectorPage() {
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [rows, setRows] = useState<LlmInvocation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [live, setLive] = useState(true);
  const [follow, setFollow] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<"all" | "pidgin_chat" | "slack">(
    "all",
  );
  // "Clear" hides everything recorded before a watermark id; the rows stay in
  // the database and the rest of the app — this only resets the view.
  const storageKey = `llm-inspector-cleared:${slug}`;
  const [clearedBefore, setClearedBefore] = useState<string | null>(() =>
    slug ? window.localStorage.getItem(`llm-inspector-cleared:${slug}`) : null,
  );
  // Refs mirror state the poll loop reads, so the interval never restarts.
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const followRef = useRef(follow);
  followRef.current = follow;
  const clearedRef = useRef(clearedBefore);
  clearedRef.current = clearedBefore;

  const merge = useCallback((incoming: LlmInvocation[]) => {
    if (incoming.length === 0) return;
    setRows((current) => {
      const seen = new Set(current.map((row) => row.id));
      const fresh = incoming.filter((row) => !seen.has(row.id));
      if (fresh.length === 0) return current;
      const next = [...fresh, ...current].slice(0, MAX_ROWS);
      if (followRef.current) {
        setSelectedId(next[0].id);
      }
      return next;
    });
  }, []);

  const poll = useCallback(async () => {
    if (!slug) return;
    try {
      const newest = rowsRef.current[0]?.id ?? clearedRef.current ?? undefined;
      const incoming = await api.listLlmInvocations(slug, {
        limit: 100,
        after: newest,
      });
      merge(incoming);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load invocations");
    }
  }, [slug, merge]);

  useEffect(() => {
    void poll();
  }, [poll]);

  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => void poll(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [live, poll]);

  function handleClear() {
    const newest = rows[0]?.id;
    if (newest) {
      window.localStorage.setItem(storageKey, newest);
      setClearedBefore(newest);
    }
    setRows([]);
    setSelectedId(null);
    setFollow(true);
  }

  function handleShowHistory() {
    window.localStorage.removeItem(storageKey);
    setClearedBefore(null);
    clearedRef.current = null;
    setRows([]);
    setSelectedId(null);
    rowsRef.current = [];
    void poll();
  }

  const selected = rows.find((row) => row.id === selectedId) ?? null;
  const visibleRows =
    sourceFilter === "all"
      ? rows
      : rows.filter((row) => row.source === sourceFilter);

  const filters: Array<{ key: typeof sourceFilter; label: string }> = [
    { key: "all", label: "All" },
    { key: "pidgin_chat", label: "Chat" },
    { key: "slack", label: "Slack" },
  ];

  return (
    <div className="stack llm-inspector">
      <div className="page-header">
        <h2>LLM Inspector</h2>
        <div className="page-header-actions">
          <button
            type="button"
            className={live ? "" : "secondary"}
            onClick={() => setLive((v) => !v)}
          >
            {live ? "● Live" : "Paused"}
          </button>
          <button
            type="button"
            className={follow ? "" : "secondary"}
            onClick={() => setFollow((v) => !v)}
          >
            Follow latest
          </button>
          <button
            type="button"
            className="secondary"
            onClick={handleClear}
            disabled={rows.length === 0}
          >
            Clear
          </button>
          {clearedBefore ? (
            <button type="button" className="secondary" onClick={handleShowHistory}>
              Show history
            </button>
          ) : null}
        </div>
      </div>
      <p className="muted">
        Every request and response between agents and the LLM, across all channels
        (Slack, chat, voice, timers). Talk to an agent and watch calls appear here.
      </p>

      {error ? <div className="error">{error}</div> : null}

      <div className="llm-split">
        <div className="llm-list">
          <div className="llm-filter-bar">
            {filters.map((f) => (
              <button
                key={f.key}
                type="button"
                className={sourceFilter === f.key ? "llm-filter active" : "llm-filter"}
                onClick={() => setSourceFilter(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>
          {visibleRows.length === 0 ? (
            <p className="muted">
              {rows.length > 0
                ? "No calls match this filter."
                : clearedBefore
                  ? "View cleared — waiting for new calls."
                  : "No LLM calls recorded yet."}
            </p>
          ) : (
            visibleRows.map((row) => (
              <button
                key={row.id}
                type="button"
                className={
                  row.id === selectedId
                    ? "llm-list-item selected"
                    : row.error_text
                      ? "llm-list-item failed"
                      : "llm-list-item"
                }
                onClick={() => {
                  setSelectedId(row.id);
                  setFollow(false);
                }}
              >
                <div className="llm-list-item-top">
                  <span>{formatTime(row.invoked_at)}</span>
                  <span className={`llm-source-badge llm-source-${row.source}`}>
                    {row.source}
                  </span>
                </div>
                <div className="llm-list-item-mid">
                  req-{row.id.slice(-6).toLowerCase()} ·{" "}
                  {row.agent_display_name ?? "unknown"} · #{row.sequence_in_turn}
                </div>
                <div className="llm-list-item-bottom muted">
                  {row.input_tokens.toLocaleString()}→
                  {row.output_tokens.toLocaleString()} tok
                  {row.latency_ms != null ? ` · ${row.latency_ms} ms` : ""}
                  {row.error_text ? " · ERROR" : ""}
                </div>
              </button>
            ))
          )}
        </div>
        <div className="llm-detail-pane">
          {selected ? (
            <InvocationDetail invocation={selected} slug={slug} />
          ) : (
            <p className="muted">Select an invocation to inspect it.</p>
          )}
        </div>
      </div>
    </div>
  );
}
