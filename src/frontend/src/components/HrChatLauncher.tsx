import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../api/client";
import { ChatView } from "./ChatView";
import { useApp } from "../context/AppContext";

const HR_HANDLE = "hr";

/**
 * Always-available HR assistant. A floating launcher in the bottom-right opens
 * a docked chat with the pre-hired HR agent, on any page. Hidden on the HR
 * agent's own full chat screen (you're already there).
 */
export function HrChatLauncher() {
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [hr, setHr] = useState<{ display_name: string } | null>(null);

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    void api
      .getAgent(slug, HR_HANDLE)
      .then((agent) => {
        if (!cancelled) setHr({ display_name: agent.display_name });
      })
      .catch(() => {
        if (!cancelled) setHr(null);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  // Don't show the floating launcher on the HR agent's own chat page.
  const onHrChat = location.pathname.endsWith(`/agents/${HR_HANDLE}/chat`);
  if (!slug || !hr || onHrChat) return null;

  const initial = hr.display_name.charAt(0).toUpperCase();

  return (
    <>
      {open ? (
        <div className="hr-launcher-panel">
          <div className="hr-launcher-panel-head">
            <div className="hr-launcher-head-agent">
              <span className="hr-launcher-avatar">{initial}</span>
              <div>
                <div className="hr-launcher-head-name">{hr.display_name}</div>
                <div className="hr-launcher-head-sub">HR · here to help you hire</div>
              </div>
            </div>
            <button
              type="button"
              className="hr-launcher-close"
              onClick={() => setOpen(false)}
              aria-label="Close HR chat"
            >
              ✕
            </button>
          </div>
          <div className="hr-launcher-panel-body">
            <ChatView
              slug={slug}
              agentHandle={HR_HANDLE}
              agentDisplayName={hr.display_name}
              inModal
              compact
            />
          </div>
        </div>
      ) : null}
      <button
        type="button"
        className={`hr-launcher-fab${open ? " is-open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Close HR chat" : "Ask HR"}
      >
        {open ? (
          "✕"
        ) : (
          <>
            <span className="hr-launcher-fab-avatar">{initial}</span>
            <span className="hr-launcher-fab-label">Ask HR</span>
          </>
        )}
      </button>
    </>
  );
}
