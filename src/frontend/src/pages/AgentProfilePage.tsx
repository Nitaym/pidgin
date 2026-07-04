import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Agent, type AuditEntry } from "../api/client";
import { BriefForm } from "../components/BriefForm";
import { ConfirmModal } from "../components/ConfirmModal";
import { HrAssistPanel } from "../components/HrAssistPanel";
import { useApp } from "../context/AppContext";
import { emptyCustomization, type HireCustomization } from "../types/hire";

function agentStatusLabel(status: string): string {
  return status === "offboarded" ? "archived" : status;
}

const OUTCOME_LABELS: Record<string, string> = {
  executed: "done",
  staged: "awaiting approval",
  refused: "refused",
  failed: "failed",
};

function summarizeAction(entry: AuditEntry): string {
  const p = entry.action_params;
  const params = p && typeof p === "object" ? (p as Record<string, unknown>) : {};
  const str = (v: unknown) => (typeof v === "string" ? v : undefined);
  if (entry.action_type === "execute") {
    const kind = str(params.kind) ?? "file";
    const name = str(params.name) ?? "(unnamed)";
    const target = str(params.resource_uri) ?? "";
    return `create ${kind} “${name}”${target ? ` in ${target}` : ""}`;
  }
  if (entry.action_type === "say" || entry.action_type === "post") {
    const text = str(params.text) ?? "";
    return text.length > 80 ? `${text.slice(0, 80)}…` : text;
  }
  if (entry.action_type === "read") return str(params.resource_uri) ?? "read";
  const keys = Object.keys(params);
  return keys.length ? `${keys.map((k) => `${k}=${String(params[k])}`).join(", ")}` : "";
}

function ActionLogPanel({ slug, agentId }: { slug: string; agentId: string }) {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setEntries(await api.listAudit(slug, { agentId, limit: 100 }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load action log");
    }
  }, [slug, agentId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className="panel stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h4 style={{ margin: 0 }}>Action log</h4>
        <button type="button" className="secondary" onClick={() => void refresh()}>
          Refresh
        </button>
      </div>
      <p className="muted" style={{ margin: 0 }}>
        Every action this agent proposed and what the policy gate did with it.
      </p>
      {error ? <div className="error">{error}</div> : null}
      {entries === null ? (
        <p className="muted">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="muted">No actions recorded yet.</p>
      ) : (
        <ul className="action-log" style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {entries.map((entry) => (
            <li
              key={entry.id}
              className="row"
              style={{
                gap: "0.75rem",
                alignItems: "baseline",
                padding: "0.4rem 0",
                borderTop: "1px solid var(--border, #2a2a2a)",
              }}
            >
              <span className="muted" style={{ fontFamily: "monospace", fontSize: "0.8rem" }}>
                {new Date(entry.occurred_at).toLocaleString()}
              </span>
              <span style={{ fontWeight: 600 }}>{entry.action_type}</span>
              <span className={`badge outcome-${entry.outcome}`}>
                {OUTCOME_LABELS[entry.outcome] ?? entry.outcome}
              </span>
              <span className="muted" style={{ flex: 1, minWidth: 0 }}>
                {summarizeAction(entry)}
              </span>
              <Link to={`../../debug/turns/${entry.turn_id}`} className="muted">
                turn
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function AgentProfilePage() {
  const { handle = "" } = useParams();
  const navigate = useNavigate();
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";

  const [agent, setAgent] = useState<Agent | null>(null);
  const [customization, setCustomization] = useState<HireCustomization>(emptyCustomization());
  const [savedCustomization, setSavedCustomization] = useState<HireCustomization>(
    emptyCustomization(),
  );
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [showCreateTemplate, setShowCreateTemplate] = useState(false);
  const [showArchiveConfirm, setShowArchiveConfirm] = useState(false);
  const [archiveError, setArchiveError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!slug || !handle) return;
    const brief = await api.getAgentBrief(slug, handle);

    if (brief.display_name) {
      setAgent({
        id: brief.id,
        display_name: brief.display_name,
        role_title: brief.role_title,
        handle: brief.handle,
        current_status: brief.current_status,
        created_at: brief.created_at,
      });
    } else {
      const agents = await api.listAgents(slug);
      const row = agents.find((a) => a.handle === handle);
      if (!row) {
        try {
          setAgent(await api.getAgent(slug, handle));
        } catch {
          throw new Error("Agent not found");
        }
      } else {
        setAgent(row);
      }
    }

    const custom = brief.customization ?? emptyCustomization();
    setCustomization(custom);
    setSavedCustomization(custom);
  }, [slug, handle]);

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, [load]);

  async function handleSaveBrief() {
    if (!slug || !handle) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.patchAgentBrief(slug, handle, customization);
      setSavedCustomization(result.customization);
      setMessage("Brief saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateTemplate(event: React.FormEvent) {
    event.preventDefault();
    if (!slug || !handle || !templateName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.createTemplateFromAgent(slug, handle, {
        name: templateName.trim(),
      });
      setShowCreateTemplate(false);
      // "Your Templates" page was removed; saved profiles live in the marketplace.
      navigate(`/${slug}/hire/marketplace`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create template failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleArchive() {
    if (!slug || !handle) return;
    setBusy(true);
    setArchiveError(null);
    setError(null);
    setMessage(null);
    try {
      const result = await api.archiveAgent(slug, handle);
      setAgent((prev) =>
        prev ? { ...prev, current_status: result.current_status } : prev,
      );
      setShowArchiveConfirm(false);
      setArchiveError(null);
      navigate(`/${slug}/`, { replace: true });
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Archive failed";
      setArchiveError(detail);
    } finally {
      setBusy(false);
    }
  }

  function openArchiveConfirm() {
    setArchiveError(null);
    setShowArchiveConfirm(true);
  }

  function closeArchiveConfirm() {
    if (busy) return;
    setArchiveError(null);
    setShowArchiveConfirm(false);
  }

  if (!agent) {
    return (
      <div className="stack">
        {error ? <div className="error">{error}</div> : <p className="muted">Loading…</p>}
      </div>
    );
  }

  const archived = agent.current_status === "offboarded";
  const dirty = JSON.stringify(customization) !== JSON.stringify(savedCustomization);

  return (
    <div className="stack">
      <Link to=".." className="muted">
        ← Team
      </Link>

      <div className="hero panel stack">
        <div className="row profile-hero">
          <div>
            <h3 style={{ margin: 0 }}>{agent.display_name}</h3>
            <p className="muted" style={{ margin: 0 }}>
              {agent.role_title} · @{agent.handle} · {agentStatusLabel(agent.current_status)}
            </p>
          </div>
          {!archived ? (
            <Link to={`chat`} className="btn">
              Open chat
            </Link>
          ) : null}
        </div>
      </div>

      {archived ? (
        <div className="warning">
          This agent is archived. They no longer appear on your team or respond to messages.
        </div>
      ) : null}

      {error ? <div className="error">{error}</div> : null}
      {message ? <div className="success">{message}</div> : null}

      <ConfirmModal
        open={showArchiveConfirm}
        title="Archive this agent?"
        busy={busy}
        error={archiveError}
        confirmLabel={busy ? "Archiving…" : "Archive agent"}
        onClose={closeArchiveConfirm}
        onConfirm={() => void handleArchive()}
      >
        <p style={{ margin: 0 }}>
          {agent.display_name} will be removed from your team and will no longer respond to messages.
          Their brief, history, and audit trail are kept on disk.
        </p>
        <p style={{ margin: 0 }}>This cannot be undone from the UI.</p>
      </ConfirmModal>

      <div className="split-layout">
        <div className="panel stack">
          <h4 style={{ margin: 0 }}>Role brief</h4>
          <BriefForm value={customization} onChange={setCustomization} />
          <div className="row profile-actions">
            <button
              type="button"
              disabled={busy || !dirty || archived}
              onClick={() => void handleSaveBrief()}
            >
              Save brief
            </button>
            <button
              type="button"
              className="secondary"
              disabled={archived}
              onClick={() => setShowCreateTemplate((v) => !v)}
            >
              Create template from this agent
            </button>
            {!archived ? (
              <button
                type="button"
                className="danger profile-actions-danger"
                disabled={busy}
                onClick={openArchiveConfirm}
              >
                Archive agent
              </button>
            ) : null}
          </div>
          {showCreateTemplate ? (
            <form className="stack" onSubmit={(e) => void handleCreateTemplate(e)}>
              <label className="field">
                New template name
                <input
                  value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                  placeholder="Our tuned support playbook"
                  required
                />
              </label>
              <button type="submit" disabled={busy}>
                Save as Your role template
              </button>
            </form>
          ) : null}
        </div>

        {!archived ? (
          <HrAssistPanel
            slug={slug}
            contextType="agent"
            contextId={agent.id}
            customization={customization}
            onApplyCustomization={setCustomization}
          />
        ) : null}
      </div>

      <ActionLogPanel slug={slug} agentId={agent.id} />
    </div>
  );
}
