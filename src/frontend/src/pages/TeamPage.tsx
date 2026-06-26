import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Agent } from "../api/client";
import { useApp } from "../context/AppContext";

export function TeamPage() {
  const { workspace, user, refresh } = useApp();
  const slug = workspace?.slug ?? "";
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadTeam = useCallback(async () => {
    if (!slug) return;
    setError(null);
    setAgents(await api.listAgents(slug));
  }, [slug]);

  useEffect(() => {
    void loadTeam().catch((err: Error) => setError(err.message));
  }, [loadTeam]);

  async function handleLogout() {
    await api.logout();
    await refresh();
    window.location.href = "/login";
  }

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h2>{workspace?.display_name ?? "Team"}</h2>
          <p className="muted" style={{ margin: "4px 0 0" }}>
            Signed in as {user?.name || user?.email}
          </p>
        </div>
        <div className="page-header-actions">
          <button type="button" className="secondary" onClick={() => void handleLogout()}>
            Sign out
          </button>
        </div>
      </div>

      {error ? <div className="error">{error}</div> : null}

      <section className="stack">
        <h3 style={{ margin: 0 }}>Your AI team</h3>
        {agents.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon" aria-hidden="true">
              <span />
              <span />
              <span />
              <span />
            </div>
            <h3>No agents yet</h3>
            <p>Hire your first AI employee from a role template to get started.</p>
          </div>
        ) : (
          <div className="team-grid">
            {agents.map((agent) => {
              const archived = agent.current_status === "offboarded";
              return (
                <div key={agent.id} className="panel team-card">
                  <div className="team-card-head">
                    <Link to={`agents/${agent.handle}`} className="team-card-name">
                      {agent.display_name}
                    </Link>
                    {agent.is_preseeded ? (
                      <span className="chip team-preseeded-chip">Preseeded</span>
                    ) : null}
                  </div>
                  <p className="muted team-card-meta">
                    {agent.role_title} · @{agent.handle} · {archived ? "archived" : agent.current_status}
                  </p>
                  {agent.preseeded_blurb ? (
                    <p className="team-card-blurb">{agent.preseeded_blurb}</p>
                  ) : null}
                  <div className="team-card-foot">
                    {!archived ? (
                      <Link
                        to={`agents/${agent.handle}/chat`}
                        className="btn secondary team-chat-btn"
                      >
                        Chat
                      </Link>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <Link to="hire" className="btn" style={{ alignSelf: "flex-start" }}>
        Hire a role
      </Link>
    </div>
  );
}
