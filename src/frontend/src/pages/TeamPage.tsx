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

      <section className="panel stack">
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
          <ul className="list-links">
            {agents.map((agent) => (
              <li key={agent.id}>
                <Link to={`agents/${agent.handle}`}>{agent.display_name}</Link>
                <span className="muted">
                  {" "}
                  — {agent.role_title} (@{agent.handle}) ·{" "}
                  {agent.current_status === "offboarded" ? "archived" : agent.current_status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Link to="hire" className="btn" style={{ alignSelf: "flex-start" }}>
        Hire a role
      </Link>
    </div>
  );
}
