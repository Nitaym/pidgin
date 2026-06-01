import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { BriefForm } from "../components/BriefForm";
import { HrAssistPanel } from "../components/HrAssistPanel";
import { useApp } from "../context/AppContext";
import { emptyCustomization, type HireCustomization } from "../types/hire";

export function TemplatesPage() {
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [templates, setTemplates] = useState<
    Awaited<ReturnType<typeof api.listRoleTemplates>>["workspace"]
  >([]);

  useEffect(() => {
    if (!slug) return;
    void api.listRoleTemplates(slug).then((r) => setTemplates(r.workspace));
  }, [slug]);

  return (
    <div className="stack">
      <div className="page-header">
        <h2>Your role templates</h2>
      </div>
      <div className="panel stack">
        {templates.length === 0 ? (
          <p className="muted">
            No workspace templates yet.{" "}
            <Link to="../hire">Hire a role</Link> and duplicate a Pidgin template, or create one
            from an agent profile.
          </p>
        ) : (
          <ul>
            {templates.map((t) => (
              <li key={t.slug}>
                <Link to={t.slug}>
                  {t.name} — v{t.current_version}
                </Link>
                <span className="muted"> · updated {t.updated_at}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function TemplateEditorPage() {
  const { templateSlug = "" } = useParams();
  const navigate = useNavigate();
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";

  const [name, setName] = useState("");
  const [version, setVersion] = useState(1);
  const [customization, setCustomization] = useState<HireCustomization>(emptyCustomization());
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!slug || !templateSlug) return;
    const detail = await api.getWorkspaceTemplate(slug, templateSlug);
    setName(detail.name);
    setVersion(detail.current_version);
    setCustomization(detail.customization);
  }, [slug, templateSlug]);

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, [load]);

  async function handleSave() {
    if (!slug || !templateSlug) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const saved = await api.saveWorkspaceTemplate(slug, templateSlug, {
        name: name.trim() || undefined,
        customization,
      });
      setVersion(saved.current_version);
      setName(saved.name);
      setCustomization(saved.customization);
      setMessage(`Saved as version ${saved.current_version}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (!slug || !templateSlug) return;
    if (!window.confirm(`Delete template "${name}" and all versions?`)) return;
    setBusy(true);
    try {
      await api.deleteWorkspaceTemplate(slug, templateSlug);
      navigate("../templates");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <Link to="../templates" className="muted">
        ← Templates
      </Link>

      <div className="panel stack">
        <p className="eyebrow">Your role template · v{version}</p>
        <label className="field">
          Template name
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        {error ? <div className="error">{error}</div> : null}
        {message ? <div className="success">{message}</div> : null}
      </div>

      <div className="split-layout">
        <div className="panel stack">
          <BriefForm value={customization} onChange={setCustomization} />
          <div className="row">
            <button type="button" disabled={busy} onClick={() => void handleSave()}>
              Save template (new version)
            </button>
            <button type="button" className="secondary" disabled={busy} onClick={() => void handleDelete()}>
              Delete template
            </button>
          </div>
        </div>
        <HrAssistPanel
          slug={slug}
          contextType="template"
          contextId={templateSlug}
          customization={customization}
          onApplyCustomization={setCustomization}
        />
      </div>
    </div>
  );
}
