import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { BriefForm } from "../components/BriefForm";
import { HrAssistPanel } from "../components/HrAssistPanel";
import { useApp } from "../context/AppContext";
import {
  emptyCustomization,
  type HireCustomization,
  type SelectedTemplate,
} from "../types/hire";

function suggestHandle(displayName: string): string {
  return displayName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function HireWizardPage() {
  const navigate = useNavigate();
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";

  const [step, setStep] = useState(1);
  const [templates, setTemplates] = useState<Awaited<
    ReturnType<typeof api.listRoleTemplates>
  > | null>(null);
  const [selected, setSelected] = useState<SelectedTemplate | null>(null);
  const [customization, setCustomization] = useState<HireCustomization>(emptyCustomization());
  const [displayName, setDisplayName] = useState("");
  const [handle, setHandle] = useState("");
  const [handleEdited, setHandleEdited] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const hireContextId = useMemo(() => `hire-${Date.now()}`, []);

  const loadTemplates = useCallback(async () => {
    if (!slug) return;
    setTemplates(await api.listRoleTemplates(slug));
  }, [slug]);

  useEffect(() => {
    void loadTemplates().catch((err: Error) => setError(err.message));
  }, [loadTemplates]);

  useEffect(() => {
    if (!handleEdited && displayName) {
      setHandle(suggestHandle(displayName));
    }
  }, [displayName, handleEdited]);

  async function selectBundled(templateId: string, name: string) {
    setBusy(true);
    setError(null);
    try {
      const detail = await api.getBundledTemplate(slug, templateId);
      setSelected({ source: "bundled", templateId, name, version: detail.version });
      setCustomization({
        job_requirements: detail.default_job_requirements,
        ideal_candidate: detail.default_ideal_candidate,
        your_take: "",
      });
      setStep(2);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load template");
    } finally {
      setBusy(false);
    }
  }

  async function selectWorkspace(templateSlug: string, name: string, version: number) {
    setBusy(true);
    setError(null);
    try {
      const detail = await api.getWorkspaceTemplate(slug, templateSlug);
      setSelected({ source: "workspace", slug: templateSlug, name, version });
      setCustomization(detail.customization);
      setStep(2);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load template");
    } finally {
      setBusy(false);
    }
  }

  async function duplicateBundled(templateId: string, name: string) {
    setBusy(true);
    setError(null);
    try {
      const created = await api.createWorkspaceTemplate(slug, {
        name: `${name} (copy)`,
        duplicate_from_recipe_id: templateId,
      });
      await loadTemplates();
      setSelected({
        source: "workspace",
        slug: created.slug,
        name: created.name,
        version: created.current_version,
      });
      setCustomization(created.customization);
      setStep(2);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Duplicate failed");
    } finally {
      setBusy(false);
    }
  }

  function startBlank() {
    setSelected({ source: "blank", name: "Custom role" });
    setCustomization(emptyCustomization());
    setStep(2);
  }

  async function handleHire() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      let body: Parameters<typeof api.hireAgent>[1];
      if (selected.source === "bundled") {
        body = {
          template_source: "bundled",
          template_id: selected.templateId,
          customization,
          display_name: displayName.trim(),
          handle: handle.trim() || undefined,
        };
      } else if (selected.source === "workspace") {
        body = {
          template_source: "workspace",
          slug: selected.slug,
          customization,
          display_name: displayName.trim(),
          handle: handle.trim() || undefined,
        };
      } else {
        body = {
          template_source: "bundled",
          template_id: "executive-assistant",
          customization,
          display_name: displayName.trim(),
          handle: handle.trim() || undefined,
        };
      }
      const result = await api.hireAgent(slug, body);
      navigate(`../agents/${result.handle}`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hire failed");
    } finally {
      setBusy(false);
    }
  }

  const templateLabel =
    selected?.source === "bundled"
      ? `Pidgin role template: ${selected.name} v${selected.version}`
      : selected?.source === "workspace"
        ? `Your role template: ${selected.name} v${selected.version}`
        : selected?.source === "blank"
          ? "Blank custom role"
          : "";

  return (
    <div className="stack">
      <div className="row">
        <Link to=".." className="muted">
          ← Team
        </Link>
      </div>

      <div className="panel stack">
        <p className="eyebrow">Hire a role · Step {step} of 4</p>
        <h3 style={{ margin: 0 }}>Hire a role</h3>
        {error ? <div className="error">{error}</div> : null}

        {step === 1 ? (
          <div className="stack">
            <section className="stack">
              <h4 style={{ margin: 0 }}>Pidgin role templates</h4>
              <div className="template-grid">
                {(templates?.bundled ?? []).map((t) => (
                  <div key={t.template_id} className="template-card panel stack">
                    <strong>{t.name}</strong>
                    <span className="muted">{t.role_title}</span>
                    <span className="muted">v{t.version}</span>
                    <div className="row">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void selectBundled(t.template_id, t.name)}
                      >
                        Use this template
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        disabled={busy}
                        onClick={() => void duplicateBundled(t.template_id, t.name)}
                      >
                        Duplicate
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="stack">
              <h4 style={{ margin: 0 }}>Your role templates</h4>
              {(templates?.workspace ?? []).length === 0 ? (
                <p className="muted">None yet — duplicate a Pidgin template or create from an agent.</p>
              ) : (
                <div className="template-grid">
                  {templates?.workspace.map((t) => (
                    <div key={t.slug} className="template-card panel stack">
                      <strong>{t.name}</strong>
                      <span className="muted">v{t.current_version}</span>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void selectWorkspace(t.slug, t.name, t.current_version)}
                      >
                        Use this template
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <button type="button" className="secondary" disabled={busy} onClick={startBlank}>
              Create blank template
            </button>
          </div>
        ) : null}

        {step === 2 ? (
          <div className="split-layout">
            <BriefForm value={customization} onChange={setCustomization} />
            <HrAssistPanel
              slug={slug}
              contextType="hire"
              contextId={hireContextId}
              customization={customization}
              onApplyCustomization={setCustomization}
            />
          </div>
        ) : null}

        {step === 3 ? (
          <div className="stack">
            <label className="field">
              Agent display name
              <input
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="Jane"
                required
              />
            </label>
            <label className="field">
              Handle
              <input
                value={handle}
                onChange={(e) => {
                  setHandleEdited(true);
                  setHandle(e.target.value);
                }}
                placeholder="jane"
              />
            </label>
            <p className="muted field-hint">Manager defaults to you (workspace operator).</p>
          </div>
        ) : null}

        {step === 4 ? (
          <div className="stack">
            <p className="muted">{templateLabel}</p>
            <dl className="review-list">
              <dt>Display name</dt>
              <dd>{displayName}</dd>
              <dt>Handle</dt>
              <dd>@{handle}</dd>
              <dt>Mission</dt>
              <dd>{customization.job_requirements.mission || "—"}</dd>
              <dt>Tone</dt>
              <dd>{customization.ideal_candidate.tone || "—"}</dd>
              <dt>Your take</dt>
              <dd>{customization.your_take || "—"}</dd>
            </dl>
          </div>
        ) : null}

        {step > 1 ? (
          <div className="row">
            <button type="button" className="secondary" onClick={() => setStep((s) => s - 1)}>
              Back
            </button>
            {step < 4 ? (
              <button
                type="button"
                onClick={() => setStep((s) => s + 1)}
                disabled={step === 3 && !displayName.trim()}
              >
                Continue
              </button>
            ) : (
              <button type="button" disabled={busy} onClick={() => void handleHire()}>
                {busy ? "Hiring…" : "Hire and continue"}
              </button>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
