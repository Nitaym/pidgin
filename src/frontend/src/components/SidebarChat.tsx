import { useEffect, useState } from "react";
import { api, type Agent } from "../api/client";
import { ChatModal } from "./ChatModal";

type SidebarChatProps = {
  slug: string;
  base: string;
};

export function SidebarChat({ slug, base: _base }: SidebarChatProps) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [chatOpen, setChatOpen] = useState(false);

  useEffect(() => {
    if (!slug) return;
    void api.listAgents(slug).then(setAgents).catch(() => setAgents([]));
  }, [slug]);

  // Show every active agent — a freshly hired one has no conversation_id yet;
  // the conversation is created on the first message.
  const chatAgents = agents.filter(
    (agent) => agent.current_status !== "offboarded",
  );

  if (chatAgents.length === 0) return null;

  return (
    <>
      <div className="sidebar-section">
        <p className="sidebar-section-label">Chat</p>
        <button
          className="sidebar-chat-btn"
          onClick={() => setChatOpen(true)}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="sidebar-chat-icon">
            <path d="M14 1H2a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h2v3l3-3h7a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1z" fill="currentColor" opacity=".9"/>
          </svg>
          Messages
          <span className="sidebar-chat-badge">{chatAgents.length}</span>
        </button>
      </div>

      {chatOpen && <ChatModal onClose={() => setChatOpen(false)} />}
    </>
  );
}
