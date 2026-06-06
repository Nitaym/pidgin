import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { randomAmericanFirstName } from "../utils/agentNameGenerator";

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

  const [step, setStep] = useState<1 | 2>(1);
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
  const displayNameSeeded = useRef(false);

  const hireContextId = useMemo(() => `hire-${Date.now()}`, []);

  const chooseRandomDisplayName = useCallback(() => {
    const name = randomAmericanFirstName();
    setDisplayName(name);
    if (!handleEdited) {
      setHandle(suggestHandle(name));
    }
  }, [handleEdited]);

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

  useEffect(() => {
    if (step === 2 && !displayNameSeeded.current) {
      displayNameSeeded.current = true;
      chooseRandomDisplayName();
    }
  }, [step, chooseRandomDisplayName]);

  function goToDetails(next: SelectedTemplate, customizationNext: HireCustomization) {
    setSelected(next);
    setCustomization(customizationNext);
    setStep(2);
  }

  async function selectBundled(templateId: string, name: string) {
    setBusy(true);
    setError(null);
    try {
      const detail = await api.getBundledTemplate(slug, templateId);
      goToDetails(
        { source: "bundled", templateId, name, version: detail.version },
        {
          job_requirements: detail.default_job_requirements,
          ideal_candidate: detail.default_ideal_candidate,
          your_take: "",
        },
      );
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
      goToDetails(
        { source: "workspace", slug: templateSlug, name, version },
        detail.customization,
      );
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
      goToDetails(
        {
          source: "workspace",
          slug: created.slug,
          name: created.name,
          version: created.current_version,
        },
        created.customization,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Duplicate failed");
    } finally {
      setBusy(false);
    }
  }

  function startFresh() {
    goToDetails({ source: "blank", name: "Start fresh" }, emptyCustomization());
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
      navigate(`../agents/${result.handle}/chat`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hire failed");
    } finally {
      setBusy(false);
    }
  }

  const templateLabel =
    selected?.source === "bundled"
      ? `${selected.name} v${selected.version}`
      : selected?.source === "workspace"
        ? `${selected.name} v${selected.version}`
        : selected?.source === "blank"
          ? "Start fresh"
          : "";

  const canHire = Boolean(selected && displayName.trim());

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <p className="eyebrow" style={{ margin: "0 0 4px" }}>
            {step === 1 ? "Step 1 of 2 · Choose a template" : "Step 2 of 2 · Agent details"}
          </p>
          <h2>Hire a role</h2>
        </div>
        <Link to=".." className="ghost">
          ← Team
        </Link>
      </div>

      {error ? <div className="error">{error}</div> : null}

      {step === 1 ? (
        <div className="stack">
          <section className="brief-section">
            <h3 className="brief-section-title">Pidgin role templates</h3>
            <p className="muted field-hint">
              Pick a starting point for this hire. You can edit everything on the next screen.
            </p>
            <div className="template-grid">
              {(templates?.bundled ?? []).map((t) => (
                <div key={t.template_id} className="template-card panel stack">
                  <strong>{t.name}</strong>
                  <span className="muted">{t.role_title}</span>
                  <span className="muted">v{t.version}</span>
                  {t.description ? <span className="muted">{t.description}</span> : null}
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

          {(templates?.workspace ?? []).length > 0 ? (
            <section className="brief-section">
              <h3 className="brief-section-title">Your role templates</h3>
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
            </section>
          ) : null}

          <section className="brief-section">
            <h3 className="brief-section-title">Start fresh</h3>
            <p className="muted field-hint">
              No template defaults — write the role brief from scratch.
            </p>
            <button type="button" className="secondary" disabled={busy} onClick={startFresh}>
              Start fresh
            </button>
          </section>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="split-layout hire-page">
          <div className="stack hire-page-main">
            <p className="review-template">
              Based on: <strong>{templateLabel}</strong>
              {" · "}
              <button
                type="button"
                className="ghost"
                disabled={busy}
                onClick={() => setStep(1)}
              >
                Change template
              </button>
            </p>

            <section className="brief-section">
              <h3 className="brief-section-title">Identity</h3>
              <div className="field">
                <label htmlFor="hire-display-name">Display name</label>
                <div className="field-inline">
                  <input
                    id="hire-display-name"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="Jane"
                    required
                  />
                  <button type="button" className="secondary" onClick={chooseRandomDisplayName}>
                    Choose random name
                  </button>
                </div>
              </div>
              <div className="field">
                <label htmlFor="hire-handle">Handle</label>
                <input
                  id="hire-handle"
                  value={handle}
                  onChange={(e) => {
                    setHandleEdited(true);
                    setHandle(e.target.value);
                  }}
                  placeholder="jane"
                />
              </div>
              <p className="muted field-hint">Manager defaults to you (workspace operator).</p>
            </section>

            <BriefForm value={customization} onChange={setCustomization} />

            <div className="row hire-page-actions">
              <button type="button" className="secondary" disabled={busy} onClick={() => setStep(1)}>
                Back
              </button>
              <button type="button" disabled={busy || !canHire} onClick={() => void handleHire()}>
                {busy ? "Hiring…" : "Hire and continue"}
              </button>
            </div>
          </div>

          <HrAssistPanel
            slug={slug}
            contextType="hire"
            contextId={hireContextId}
            customization={customization}
            onApplyCustomization={setCustomization}
          />
        </div>
      ) : null}
    </div>
  );
}
