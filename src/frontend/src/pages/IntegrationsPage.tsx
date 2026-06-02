import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type IntegrationCatalogEntry, type IntegrationInstallation } from "../api/client";
import { IntegrationBrand } from "../components/IntegrationBrand";
import { useApp } from "../context/AppContext";
import { formatCapability, integrationMeta } from "../utils/integrationMeta";

export function IntegrationsPage() {
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [catalog, setCatalog] = useState<IntegrationCatalogEntry[]>([]);
  const [installations, setInstallations] = useState<IntegrationInstallation[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!slug) return;
    setError(null);
    const [cat, installed] = await Promise.all([
      api.getIntegrationsCatalog(slug),
      api.listIntegrations(slug),
    ]);
    setCatalog(cat.filter((entry) => !entry.builtin));
    setInstallations(installed);
  }, [slug]);

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, [load]);

  function installationFor(type: string) {
    return installations.find((row) => row.connector_type === type);
  }

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <p className="eyebrow" style={{ margin: "0 0 4px" }}>
            System
          </p>
          <h2>Integrations</h2>
          <p className="muted field-hint" style={{ margin: "8px 0 0" }}>
            Connect the tools your AI team works in. Each integration has its own setup page.
          </p>
        </div>
      </div>

      {error ? <div className="error">{error}</div> : null}

      <section className="brief-section">
        <h3 className="brief-section-title">Available connections</h3>
        <div className="template-grid integration-catalog-grid">
          {catalog.map((entry) => {
            const installed = installationFor(entry.connector_type);
            const meta = integrationMeta(entry);
            return (
              <Link
                key={entry.connector_type}
                to={entry.connector_type}
                className={`template-card panel stack integration-catalog-card${
                  installed?.status === "active" ? " is-connected" : ""
                }`}
              >
                <IntegrationBrand meta={meta} name={entry.name} />
                <p className="muted integration-card-desc">{entry.description}</p>
                <div className="integration-capability-row">
                  {entry.capabilities.slice(0, 3).map((cap) => (
                    <span key={cap} className="integration-capability">
                      {formatCapability(cap)}
                    </span>
                  ))}
                </div>
                <span className={`integration-status integration-status-${installed?.status ?? "idle"}`}>
                  {installed?.status === "active"
                    ? "Connected"
                    : installed?.status === "errored"
                      ? "Needs attention"
                      : "Not connected"}
                </span>
                <span className="integration-card-cta">Configure →</span>
              </Link>
            );
          })}
        </div>
      </section>
    </div>
  );
}
