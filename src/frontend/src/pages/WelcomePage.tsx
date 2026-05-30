import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";

function suggestSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function WelcomePage() {
  const navigate = useNavigate();
  const { refresh, setWorkspace } = useApp();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [step, setStep] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!slugEdited) {
      setSlug(suggestSlug(name));
    }
  }, [name, slugEdited]);

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const ws = await api.createWorkspace(name.trim(), slug.trim());
      setWorkspace(ws);
      await refresh();
      navigate(`/${ws.slug}/`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create workspace");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-screen">
      <div className="welcome-card panel stack">
        <p className="eyebrow">Step {step} of 2</p>
        <h1 style={{ margin: 0 }}>Create your company workspace</h1>
        <p className="muted">
          Pidgin runs one workspace per account. Pick a company name and a URL slug for your
          workspace (e.g. <code>/acme-corp/</code>).
        </p>

        {error ? <div className="error">{error}</div> : null}

        {step === 1 ? (
          <div className="stack">
            <ul className="wizard-list">
              <li>Hire agents from proven role recipes</li>
              <li>Chat in team rooms like #support</li>
              <li>Review turns and audit logs as you grow</li>
            </ul>
            <button type="button" onClick={() => setStep(2)}>
              Get started
            </button>
          </div>
        ) : (
          <form className="stack" onSubmit={handleCreate}>
            <label className="field">
              Company name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Acme Inc."
                required
                autoFocus
              />
            </label>
            <label className="field">
              Workspace URL
              <div className="slug-field">
                <span className="slug-prefix">/</span>
                <input
                  value={slug}
                  onChange={(e) => {
                    setSlugEdited(true);
                    setSlug(e.target.value);
                  }}
                  placeholder="acme-corp"
                  required
                  pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                  title="Lowercase letters, numbers, and hyphens only"
                />
                <span className="slug-prefix">/</span>
              </div>
              <span className="muted field-hint">
                Your app and API live here: /{slug || "your-slug"}/ and /{slug || "your-slug"}
                /api/
              </span>
            </label>
            <div className="row">
              <button type="button" className="secondary" onClick={() => setStep(1)}>
                Back
              </button>
              <button
                type="submit"
                disabled={submitting || !name.trim() || !slug.trim()}
              >
                {submitting ? "Creating…" : "Create workspace"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
