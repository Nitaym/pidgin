import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Agent } from "../api/client";
import { BriefForm } from "../components/BriefForm";
import { HrAssistPanel } from "../components/HrAssistPanel";
import { useApp } from "../context/AppContext";
import { emptyCustomization, type HireCustomization } from "../types/hire";

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

  const load = useCallback(async () => {
    if (!slug || !handle) return;
    const [agents, brief] = await Promise.all([
      api.listAgents(slug),
      api.getAgentBrief(slug, handle),
    ]);
    const row = agents.find((a) => a.handle === handle) ?? null;
    setAgent(row);
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
      const created = await api.createTemplateFromAgent(slug, handle, {
        name: templateName.trim(),
      });
      setShowCreateTemplate(false);
      navigate(`../templates/${created.slug}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create template failed");
    } finally {
      setBusy(false);
    }
  }

  if (!agent) {
    return (
      <div className="stack">
        {error ? <div className="error">{error}</div> : <p className="muted">Loading…</p>}
      </div>
    );
  }

  const dirty = JSON.stringify(customization) !== JSON.stringify(savedCustomization);

  return (
    <div className="stack">
      <Link to=".." className="muted">
        ← Team
      </Link>

      <div className="hero panel stack">
        <h3 style={{ margin: 0 }}>{agent.display_name}</h3>
        <p className="muted" style={{ margin: 0 }}>
          {agent.role_title} · @{agent.handle} · {agent.current_status}
        </p>
      </div>

      {error ? <div className="error">{error}</div> : null}
      {message ? <div className="success">{message}</div> : null}

      <div className="split-layout">
        <div className="panel stack">
          <h4 style={{ margin: 0 }}>Role brief</h4>
          <BriefForm value={customization} onChange={setCustomization} />
          <div className="row">
            <button type="button" disabled={busy || !dirty} onClick={() => void handleSaveBrief()}>
              Save brief
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => setShowCreateTemplate((v) => !v)}
            >
              Create template from this agent
            </button>
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

        <HrAssistPanel
          slug={slug}
          contextType="agent"
          contextId={agent.id}
          customization={customization}
          onApplyCustomization={setCustomization}
        />
      </div>
    </div>
  );
}
