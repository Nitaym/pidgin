import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import {
  api,
  type Agent,
  type IntegrationCatalogEntry,
  type IntegrationInstallation,
} from "../api/client";
import { IntegrationBrand } from "../components/IntegrationBrand";
import { useApp } from "../context/AppContext";
import {
  formatCapability,
  integrationMeta,
  integrationSetupGuide,
} from "../utils/integrationMeta";

type AuthTab = "oauth" | "manual";

const GOOGLE_DELEGATION_URL = "https://admin.google.com/ac/owl/domainwidedelegation";

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="integration-copy-btn"
      onClick={() => {
        void navigator.clipboard?.writeText(value);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function IntegrationDetailPage() {
  const { connectorType = "" } = useParams();
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";

  const [catalogEntry, setCatalogEntry] = useState<IntegrationCatalogEntry | null>(null);
  const [installation, setInstallation] = useState<IntegrationInstallation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [authTab, setAuthTab] = useState<AuthTab>("oauth");
  const [displayName, setDisplayName] = useState("");
  const [manualFields, setManualFields] = useState<Record<string, string>>({});
  const [healthMessage, setHealthMessage] = useState<string | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [defaultAgent, setDefaultAgent] = useState("");

  const load = useCallback(async () => {
    if (!slug || !connectorType) return;
    setError(null);
    const [catalog, installations] = await Promise.all([
      api.getIntegrationsCatalog(slug),
      api.listIntegrations(slug),
    ]);
    const entry = catalog.find((row) => row.connector_type === connectorType) ?? null;
    setCatalogEntry(entry);
    if (!entry) {
      setError("Integration not found");
    }
    const match =
      installations.find((row) => row.connector_type === connectorType) ?? null;
    setInstallation(match);
    if (connectorType === "slack") {
      const config = (match?.config_json ?? {}) as Record<string, unknown>;
      setDefaultAgent(typeof config.default_agent_handle === "string" ? config.default_agent_handle : "");
      const agentRows = await api.listAgents(slug);
      setAgents(agentRows);
    }
    if (entry) {
      setDisplayName(match?.display_name ?? entry.name);
      const next: Record<string, string> = {};
      for (const field of entry.manual_fields ?? []) {
        next[field.key] = "";
      }
      setManualFields(next);
      if (entry.auth_modes.includes("oauth2")) {
        setAuthTab("oauth");
      } else if (entry.auth_modes.includes("manual")) {
        setAuthTab("manual");
      }
    }
  }, [slug, connectorType]);

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, [load]);

  const meta = useMemo(
    () => (catalogEntry ? integrationMeta(catalogEntry) : null),
    [catalogEntry],
  );

  // Parse a pasted service-account key so we can show the operator the exact
  // Client ID / service-account email their access-grant steps need. Returns
  // null while the JSON is still incomplete (mid-paste) or absent.
  const serviceAccount = useMemo(() => {
    const raw = manualFields["service_account_json"];
    if (!raw || !raw.trim()) return null;
    try {
      const obj = JSON.parse(raw) as { client_id?: string; client_email?: string };
      if (obj.client_id || obj.client_email) {
        return {
          clientId: String(obj.client_id ?? ""),
          clientEmail: String(obj.client_email ?? ""),
        };
      }
    } catch {
      // incomplete/invalid JSON while typing — no options yet
    }
    return null;
  }, [manualFields]);

  if (!connectorType) {
    return <Navigate to="../integrations" replace />;
  }

  if (catalogEntry === null && error) {
    return (
      <div className="stack">
        <div className="error">{error}</div>
        <Link to=".." className="ghost">
          ← All integrations
        </Link>
      </div>
    );
  }

  if (catalogEntry === null) {
    return (
      <div className="auth-screen" style={{ minHeight: "40vh" }}>
        <p className="muted">Loading…</p>
      </div>
    );
  }

  if (catalogEntry.builtin) {
    return <Navigate to="../integrations" replace />;
  }

  const isConnected = installation?.status === "active";
  // Surface the connector's own health/error text: prefer the fresh result from
  // a just-run check, fall back to the last message persisted in config_json.
  const healthDetail =
    healthMessage ??
    (typeof installation?.config_json?.last_health_message === "string"
      ? (installation.config_json.last_health_message as string)
      : undefined);
  const hasOAuth = catalogEntry.auth_modes.includes("oauth2");
  const hasManual = catalogEntry.auth_modes.includes("manual");
  const setupGuide = integrationSetupGuide(connectorType);
  const oauthScopes =
    catalogEntry.oauth_scopes && catalogEntry.oauth_scopes.length > 0
      ? catalogEntry.oauth_scopes
      : ["https://www.googleapis.com/auth/drive.readonly"];

  async function handleOAuth() {
    setBusy(true);
    setError(null);
    try {
      const { authorization_url } = await api.startIntegrationOAuth(slug, connectorType);
      window.location.href = authorization_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "OAuth failed");
      setBusy(false);
    }
  }

  async function handleManualConnect() {
    setBusy(true);
    setError(null);
    try {
      await api.connectIntegrationManual(slug, connectorType, {
        display_name: displayName.trim() || catalogEntry!.name,
        fields: manualFields,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connect failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleHealth() {
    if (!installation) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.checkIntegrationHealth(slug, installation.id);
      setHealthMessage(result.message);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Health check failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleDefaultAgentChange(handle: string) {
    if (!installation) return;
    setDefaultAgent(handle);
    setBusy(true);
    setError(null);
    try {
      await api.updateIntegrationConfig(slug, installation.id, {
        default_agent_handle: handle,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleDisconnect() {
    if (!installation) return;
    if (!window.confirm(`Disconnect ${catalogEntry.name}?`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.disconnectIntegration(slug, installation.id);
      setHealthMessage(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Disconnect failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack integration-detail-page">
      <div className="page-header">
        <div>
          <p className="eyebrow" style={{ margin: "0 0 4px" }}>
            Integrations
          </p>
          <h2>{catalogEntry.name}</h2>
        </div>
        <Link to=".." className="ghost">
          ← All integrations
        </Link>
      </div>

      {error ? <div className="error">{error}</div> : null}

      <div className="stack hire-page-main integration-detail-main">
        {meta ? (
          <section className="brief-section integration-hero">
            <IntegrationBrand meta={meta} name={catalogEntry.name} size="lg" />
            <p className="muted" style={{ margin: 0 }}>
              {catalogEntry.description}
            </p>
            <div className="integration-capability-row">
              {catalogEntry.capabilities.map((cap) => (
                <span key={cap} className="integration-capability">
                  {formatCapability(cap)}
                </span>
              ))}
            </div>
          </section>
        ) : null}

        {isConnected && installation ? (
          <p className="review-template integration-status-banner">
            Connected as <strong>{installation.display_name}</strong>
            {healthMessage ? <> · {healthMessage}</> : null}
          </p>
        ) : null}

        {!isConnected && setupGuide ? (
          <section className="brief-section integration-setup-guide">
            <h3 className="brief-section-title">{setupGuide.title}</h3>
            {setupGuide.intro ? (
              <p className="muted field-hint" style={{ margin: 0 }}>
                {setupGuide.intro}
              </p>
            ) : null}
            <ol className="integration-setup-steps">
              {setupGuide.steps.map((step, i) => (
                <li key={i}>
                  <span>{step.text}</span>
                  {step.links && step.links.length > 0 ? (
                    <span className="integration-setup-links">
                      {step.links.map((link) => (
                        <a
                          key={link.href}
                          href={link.href}
                          target="_blank"
                          rel="noreferrer noopener"
                        >
                          {link.label} ↗
                        </a>
                      ))}
                    </span>
                  ) : null}
                </li>
              ))}
            </ol>
            {setupGuide.docs ? (
              <p className="muted field-hint" style={{ margin: 0 }}>
                <a
                  href={setupGuide.docs.href}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  {setupGuide.docs.label} ↗
                </a>
              </p>
            ) : null}
          </section>
        ) : null}

        {!isConnected ? (
          <section className="brief-section">
            <h3 className="brief-section-title">Connect</h3>
            <p className="muted field-hint" style={{ margin: 0 }}>
              Choose how Pidgin authenticates with {catalogEntry.name}. OAuth is recommended for
              production.
            </p>

            {hasOAuth && hasManual ? (
              <div className="tabs integration-auth-tabs" role="tablist">
                <button
                  type="button"
                  role="tab"
                  className={`tab${authTab === "oauth" ? " active" : ""}`}
                  aria-selected={authTab === "oauth"}
                  onClick={() => setAuthTab("oauth")}
                >
                  OAuth
                </button>
                <button
                  type="button"
                  role="tab"
                  className={`tab${authTab === "manual" ? " active" : ""}`}
                  aria-selected={authTab === "manual"}
                  onClick={() => setAuthTab("manual")}
                >
                  Manual setup
                </button>
              </div>
            ) : null}

            {hasOAuth && (authTab === "oauth" || !hasManual) ? (
              <div className="stack" style={{ gap: "12px" }}>
                <p className="muted field-hint" style={{ margin: 0 }}>
                  Sign in with your {catalogEntry.name} account and grant Pidgin the scopes it
                  needs. You&apos;ll return here when finished.
                </p>
                <button type="button" disabled={busy} onClick={() => void handleOAuth()}>
                  Connect with OAuth
                </button>
              </div>
            ) : null}

            {hasManual && (authTab === "manual" || !hasOAuth) ? (
              <div className="stack" style={{ gap: "16px" }}>
                <p className="integration-dev-banner">
                  Manual credentials are for local development or when OAuth is unavailable.
                </p>
                <div className="field">
                  <label htmlFor="integration-display-name">Connection name</label>
                  <input
                    id="integration-display-name"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder={catalogEntry.name}
                  />
                </div>
                {(catalogEntry.manual_fields ?? []).map((field) => (
                  <Fragment key={field.key}>
                    <div className="field">
                      <label htmlFor={`manual-${field.key}`}>{field.label}</label>
                      {field.multiline ? (
                        <textarea
                          id={`manual-${field.key}`}
                          className="integration-json-input"
                          rows={8}
                          value={manualFields[field.key] ?? ""}
                          onChange={(e) =>
                            setManualFields((prev) => ({ ...prev, [field.key]: e.target.value }))
                          }
                          autoComplete="off"
                          spellCheck={false}
                          placeholder="Paste the full service account JSON key file"
                        />
                      ) : (
                        <input
                          id={`manual-${field.key}`}
                          type={field.secret ? "password" : "text"}
                          value={manualFields[field.key] ?? ""}
                          onChange={(e) =>
                            setManualFields((prev) => ({ ...prev, [field.key]: e.target.value }))
                          }
                          autoComplete="off"
                        />
                      )}
                    </div>
                    {field.key === "service_account_json" && serviceAccount ? (
                      <div className="integration-access-options">
                        <p className="muted field-hint" style={{ margin: 0 }}>
                          Key detected. Now grant it access one of two ways:
                        </p>

                        <div className="integration-access-option">
                          <h4>Read a whole organisation</h4>
                          <p className="muted field-hint" style={{ margin: 0 }}>
                            Impersonate a user so agents read everything that user can. In the
                            Google Admin console open{" "}
                            <a
                              href={GOOGLE_DELEGATION_URL}
                              target="_blank"
                              rel="noreferrer noopener"
                            >
                              Domain-wide delegation ↗
                            </a>{" "}
                            → <strong>Add new</strong>, and authorise:
                          </p>
                          <dl className="integration-meta-list integration-access-kv">
                            <div>
                              <dt>Client ID</dt>
                              <dd>
                                <code>{serviceAccount.clientId}</code>
                                <CopyButton value={serviceAccount.clientId} />
                              </dd>
                            </div>
                            <div>
                              <dt>OAuth scopes</dt>
                              <dd>
                                {oauthScopes.map((scope) => (
                                  <code key={scope}>{scope}</code>
                                ))}
                                <CopyButton value={oauthScopes.join(", ")} />
                              </dd>
                            </div>
                          </dl>
                          <p className="muted field-hint" style={{ margin: 0 }}>
                            Then set <strong>Delegated user email</strong> below to that user.
                          </p>
                        </div>

                        <div className="integration-access-option">
                          <h4>Read a single file or folder</h4>
                          <p className="muted field-hint" style={{ margin: 0 }}>
                            Share it in Google Drive with the service account, and leave{" "}
                            <strong>Delegated user email</strong> below blank:
                          </p>
                          <dl className="integration-meta-list integration-access-kv">
                            <div>
                              <dt>Service account</dt>
                              <dd>
                                <code>{serviceAccount.clientEmail}</code>
                                <CopyButton value={serviceAccount.clientEmail} />
                              </dd>
                            </div>
                          </dl>
                        </div>
                      </div>
                    ) : null}
                  </Fragment>
                ))}
                <div className="row hire-page-actions">
                  <button type="button" disabled={busy} onClick={() => void handleManualConnect()}>
                    {busy ? "Connecting…" : "Save connection"}
                  </button>
                </div>
              </div>
            ) : null}
          </section>
        ) : null}

        {installation ? (
          <section className="brief-section">
            <h3 className="brief-section-title">Manage connection</h3>
            <dl className="integration-meta-list">
              <div>
                <dt>Status</dt>
                <dd>
                  <span className={`integration-status integration-status-${installation.status}`}>
                    {installation.status}
                  </span>
                </dd>
              </div>
              <div>
                <dt>Display name</dt>
                <dd>{installation.display_name}</dd>
              </div>
              {healthDetail ? (
                <div>
                  <dt>{installation.status === "errored" ? "Error" : "Details"}</dt>
                  <dd
                    className={`integration-health-detail${
                      installation.status === "errored" ? " integration-health-error" : ""
                    }`}
                  >
                    {healthDetail}
                  </dd>
                </div>
              ) : null}
              {installation.last_health_check_at ? (
                <div>
                  <dt>Last health check</dt>
                  <dd>{new Date(installation.last_health_check_at).toLocaleString()}</dd>
                </div>
              ) : null}
            </dl>
            {connectorType === "slack" ? (
              <div className="field">
                <label htmlFor="slack-default-agent">Default agent</label>
                <select
                  id="slack-default-agent"
                  value={defaultAgent}
                  disabled={busy}
                  onChange={(e) => void handleDefaultAgentChange(e.target.value)}
                >
                  <option value="">— none (require explicit @agent) —</option>
                  {agents.map((agent) => (
                    <option key={agent.id} value={agent.handle}>
                      {agent.display_name} ({agent.handle})
                    </option>
                  ))}
                </select>
                <p className="muted field-hint" style={{ margin: "4px 0 0" }}>
                  Messages that don&apos;t name an agent are routed here.
                </p>
              </div>
            ) : null}
            <div className="row hire-page-actions">
              <button type="button" className="secondary" disabled={busy} onClick={() => void handleHealth()}>
                Run health check
              </button>
              <button
                type="button"
                className="secondary danger"
                disabled={busy}
                onClick={() => void handleDisconnect()}
              >
                Disconnect
              </button>
            </div>
          </section>
        ) : null}
      </div>
    </div>
  );
}
