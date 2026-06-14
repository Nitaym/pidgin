import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Agent } from "../api/client";
import { BriefForm } from "../components/BriefForm";
import { ConfirmModal } from "../components/ConfirmModal";
import { HrAssistPanel } from "../components/HrAssistPanel";
import { useApp } from "../context/AppContext";
import { emptyCustomization, type HireCustomization } from "../types/hire";

function agentStatusLabel(status: string): string {
  return status === "offboarded" ? "archived" : status;
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
    </div>
  );
}
