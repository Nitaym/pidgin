import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Agent, type Room } from "../api/client";
import { useApp } from "../context/AppContext";

export function TeamPage() {
  const { workspace, user, refresh } = useApp();
  const slug = workspace?.slug ?? "";
  const [agents, setAgents] = useState<Agent[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadTeam = useCallback(async () => {
    if (!slug) return;
    setError(null);
    const [agentRows, roomRows] = await Promise.all([
      api.listAgents(slug),
      api.listRooms(slug),
    ]);
    setAgents(agentRows);
    setRooms(roomRows);
  }, [slug]);

  useEffect(() => {
    void loadTeam().catch((err: Error) => setError(err.message));
  }, [loadTeam]);

  async function handleLogout() {
    await api.logout();
    await refresh();
    window.location.href = "/login";
  }

  const supportRoom = rooms.find((room) => room.name === "#support");

  return (
    <div className="stack">
      <div className="hero panel stack">
        <p className="muted">Signed in as {user?.name || user?.email}</p>
        <h3 style={{ margin: 0 }}>{workspace?.display_name}</h3>
        <p className="muted">Your AI team lives here. Hire roles with customizable briefs.</p>
        <div className="row">
          <Link to="hire" className="btn">
            Hire a role
          </Link>
          <button type="button" className="secondary" onClick={() => void handleLogout()}>
            Sign out
          </button>
        </div>
      </div>

      {error ? <div className="error">{error}</div> : null}

      <section className="panel stack">
        <h3 style={{ margin: 0 }}>Your AI team</h3>
        {agents.length === 0 ? (
          <>
            <p className="muted">No agents hired yet. Start with Hire a role.</p>
            <Link to="hire">Open hire wizard →</Link>
          </>
        ) : (
          <ul>
            {agents.map((agent) => (
              <li key={agent.id}>
                <Link to={`agents/${agent.handle}`}>{agent.display_name}</Link>
                {" — "}
                {agent.role_title} (@{agent.handle}) · {agent.current_status}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel stack">
        <h3 style={{ margin: 0 }}>Rooms</h3>
        {rooms.length === 0 ? (
          <p className="muted">Hire an agent to create your first room.</p>
        ) : (
          <ul>
            {rooms.map((room) => (
              <li key={room.id}>
                <Link to={`rooms/${room.id}/chat`}>{room.name}</Link>
                {room.purpose ? <span className="muted"> — {room.purpose}</span> : null}
              </li>
            ))}
          </ul>
        )}
        {supportRoom ? (
          <Link to={`rooms/${supportRoom.id}/chat`}>Open #support chat →</Link>
        ) : null}
      </section>
    </div>
  );
}
