import { useEffect, useState } from "react";
import { api, type Agent } from "../api/client";
import { ChatView } from "./ChatView";
import { useApp } from "../context/AppContext";
import { markRead } from "../utils/chatUnread";

type ChatModalProps = {
  onClose: () => void;
};

export function ChatModal({ onClose }: ChatModalProps) {
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedHandle, setSelectedHandle] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    void api.listAgents(slug).then((all) => {
      // Include freshly hired agents that don't have a conversation yet — it's
      // created on the first message.
      const chatAgents = all.filter(
        (a) => a.current_status !== "offboarded",
      );
      setAgents(chatAgents);
      if (chatAgents.length > 0) {
        setSelectedHandle(chatAgents[0].handle);
      }
    });
  }, [slug]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Viewing a conversation marks it read. The cleanup re-marks on
  // close/switch so replies that arrived while it was open are covered too.
  useEffect(() => {
    if (!slug || !selectedHandle) return;
    markRead(slug, selectedHandle);
    return () => markRead(slug, selectedHandle);
  }, [slug, selectedHandle]);

  const selectedAgent = agents.find((a) => a.handle === selectedHandle) ?? null;

  return (
    <div className="chat-modal-backdrop" onClick={onClose}>
      <div className="chat-modal-window" onClick={(e) => e.stopPropagation()}>
        <aside className="chat-modal-sidebar">
          <div className="chat-modal-sidebar-header">
            <span className="chat-modal-sidebar-title">Direct Messages</span>
            <button className="chat-modal-close" onClick={onClose} aria-label="Close">✕</button>
          </div>
          <nav className="chat-modal-agent-list">
            {agents.map((agent) => {
              const initial = agent.display_name.charAt(0).toUpperCase();
              const isActive = agent.handle === selectedHandle;
              return (
                <button
                  key={agent.id}
                  className={`chat-modal-agent-item ${isActive ? "chat-modal-agent-item--active" : ""}`}
                  onClick={() => setSelectedHandle(agent.handle)}
                >
                  <div className="chat-modal-agent-dot">
                    <span className="chat-modal-agent-initial">{initial}</span>
                    <span className="chat-modal-online-dot" />
                  </div>
                  <div className="chat-modal-agent-info">
                    <span className="chat-modal-agent-name">{agent.display_name}</span>
                    <span className="chat-modal-agent-role">{agent.role_title ?? agent.handle}</span>
                  </div>
                </button>
              );
            })}
          </nav>
        </aside>

        <div className="chat-modal-main">
          {selectedAgent ? (
            <ChatView
              key={selectedAgent.handle}
              slug={slug}
              agentHandle={selectedAgent.handle}
              agentDisplayName={selectedAgent.display_name}
              backLink={undefined}
              inModal
            />
          ) : (
            <div className="chat-modal-empty-state">
              <p>Select an agent to start chatting.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
