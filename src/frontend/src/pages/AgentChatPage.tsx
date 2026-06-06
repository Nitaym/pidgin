import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ChatView } from "../components/ChatView";
import { useApp } from "../context/AppContext";

export function AgentChatPage() {
  const { handle = "" } = useParams();
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [agentName, setAgentName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      if (!slug || !handle) return;
      setError(null);
      setLoading(true);
      try {
        const agent = await api.getAgent(slug, handle);
        setAgentName(agent.display_name);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to open chat");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [slug, handle]);

  if (loading) {
    return <p className="muted">Opening chat…</p>;
  }

  if (error) {
    return (
      <div className="stack">
        <Link to={`../agents/${handle}`} className="muted">
          ← Agent profile
        </Link>
        <div className="error">{error}</div>
      </div>
    );
  }

  return (
    <ChatView
      slug={slug}
      agentHandle={handle}
      agentDisplayName={agentName ?? undefined}
      backLink={{ to: `../agents/${handle}`, label: "← Agent profile" }}
    />
  );
}
