import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type BundledTemplateDetail } from "../api/client";
import { useApp } from "../context/AppContext";

function Bullets({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="muted">—</p>;
  return (
    <ul>
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

function PermissionRow({ label, verbs }: { label: string; verbs: string[] }) {
  if (verbs.length === 0) return null;
  return (
    <div className="field">
      <span className="muted">{label}</span>
      <div className="chip-row">
        {verbs.map((verb) => (
          <span key={verb} className="chip">
            {verb}
          </span>
        ))}
      </div>
    </div>
  );
}

export function CandidateProfilePage() {
  const { templateId = "" } = useParams();
  const navigate = useNavigate();
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";

  const [detail, setDetail] = useState<BundledTemplateDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!slug || !templateId) return;
    setDetail(await api.getBundledTemplate(slug, templateId));
  }, [slug, templateId]);

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, [load]);

  function hireCandidate() {
    navigate(`/${slug}/hire/marketplace?template=${encodeURIComponent(templateId)}`);
  }

  async function duplicate() {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      await api.createWorkspaceTemplate(slug, {
        name: `${detail.name} (copy)`,
        duplicate_from_recipe_id: templateId,
      });
      // Saved profiles live in the marketplace under "Your saved profiles".
      navigate(`/${slug}/hire/marketplace`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Duplicate failed");
      setBusy(false);
    }
  }

  async function toggleArchive() {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      await api.archiveProfile(slug, "bundled", templateId, !detail.archived);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update profile");
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <div className="stack">
        <Link to={`/${slug}/hire/marketplace`} className="ghost">
          ← Marketplace
        </Link>
        <div className="error">{error}</div>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="stack">
        <p className="muted">Loading candidate…</p>
      </div>
    );
  }

  const job = detail.default_job_requirements;
  const ideal = detail.default_ideal_candidate;

  return (
    <div className="stack candidate-profile page-enter">
      <div className="page-header">
        <div>
          <p className="eyebrow" style={{ margin: "0 0 4px" }}>
            Candidate profile · v{detail.version}
            {detail.archived ? " · archived" : ""}
          </p>
          <h2>{detail.name}</h2>
          <p className="muted" style={{ margin: 0 }}>
            {detail.role_title}
          </p>
        </div>
        <Link to={`/${slug}/hire/marketplace`} className="ghost">
          ← Marketplace
        </Link>
      </div>

      {detail.description ? <p>{detail.description}</p> : null}

      <div className="row candidate-actions">
        <button type="button" disabled={busy} onClick={hireCandidate}>
          Hire {detail.name}
        </button>
        <button type="button" className="secondary" disabled={busy} onClick={() => void duplicate()}>
          Duplicate to your profiles
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => void toggleArchive()}
        >
          {detail.archived ? "Unarchive profile" : "Archive profile"}
        </button>
      </div>

      <section className="panel stack brief-section">
        <h3 className="brief-section-title">Mission</h3>
        <p>{job.mission || <span className="muted">—</span>}</p>

        <h3 className="brief-section-title">Responsibilities</h3>
        <Bullets items={job.responsibilities} />

        <h3 className="brief-section-title">Out of scope</h3>
        <Bullets items={job.out_of_scope} />
      </section>

      <section className="panel stack brief-section">
        <h3 className="brief-section-title">Ideal candidate profile</h3>
        <div className="field">
          <span className="muted">Tone</span>
          <p>{ideal.tone || <span className="muted">—</span>}</p>
        </div>
        <div className="field">
          <span className="muted">Decision framework</span>
          <p>{ideal.decision_framework || <span className="muted">—</span>}</p>
        </div>
        <div className="field">
          <span className="muted">Escalation rules</span>
          <p>{ideal.escalation_rules || <span className="muted">—</span>}</p>
        </div>
      </section>

      <section className="panel stack brief-section">
        <h3 className="brief-section-title">Access &amp; approvals</h3>
        <p className="muted field-hint">What this candidate can do once hired.</p>
        <PermissionRow label="Can do on its own" verbs={detail.permissions.can_write} />
        <PermissionRow label="Can read" verbs={detail.permissions.can_read} />
        <PermissionRow label="Needs your approval" verbs={detail.permissions.requires_approval} />
        <PermissionRow label="Blocked" verbs={detail.permissions.blocked} />
        {detail.default_channels.length > 0 ? (
          <div className="field">
            <span className="muted">Default channels</span>
            <div className="chip-row">
              {detail.default_channels.map((ch) => (
                <span key={ch} className="chip">
                  {ch}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </section>

      <div className="row candidate-actions">
        <button type="button" disabled={busy} onClick={hireCandidate}>
          Hire {detail.name}
        </button>
      </div>
    </div>
  );
}
