import { useCallback, useState } from "react";
import { NavLink, Outlet, useLocation, useParams } from "react-router-dom";
import { ChatModal } from "./ChatModal";
import { HrChatLauncher } from "./HrChatLauncher";
import { PidginLogo } from "./PidginLogo";
import { SidebarApprovals } from "./SidebarApprovals";
import { SidebarChat } from "./SidebarChat";
import { useApp } from "../context/AppContext";
import { WorkspaceEventsProvider } from "../context/WorkspaceEvents";

type LayoutProps = {
  showNav?: boolean;
};

export type LayoutOutletContext = {
  /** Opens the same Messages modal as the sidebar's "Messages" link, optionally
   * pre-selected to one agent's thread. */
  openChat: (handle?: string) => void;
};

export function Layout({ showNav = true }: LayoutProps) {
  const { workspace, user } = useApp();
  const { workspaceSlug = workspace?.slug ?? "" } = useParams();
  const onDevs = useLocation().pathname.endsWith("/devs");
  const base = workspaceSlug ? `/${workspaceSlug}` : "";
  const [chatModal, setChatModal] = useState<{ handle?: string } | null>(null);

  const openChat = useCallback((handle?: string) => setChatModal({ handle }), []);
  const closeChat = useCallback(() => setChatModal(null), []);

  const layout = (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-header">
          <PidginLogo />
          <div>
            <p className="sidebar-brand">Pidgin</p>
            {workspace ? (
              <div className="sidebar-workspace">{workspace.display_name}</div>
            ) : (
              <div className="sidebar-workspace">AI workforce</div>
            )}
          </div>
        </div>

        {showNav && workspace ? (
          <nav>
            <div className="sidebar-section">
              <p className="sidebar-section-label">Workspace</p>
              <NavLink to={base} end>
                Team
              </NavLink>
              <NavLink to={`${base}/dashboard`}>Agent Dashboard</NavLink>
            </div>
            <div className="sidebar-section">
              <p className="sidebar-section-label">Workforce</p>
              <NavLink to={`${base}/devs`}>Devs</NavLink>
              <NavLink to={`${base}/hire`}>Hire a role</NavLink>
            </div>
            <SidebarChat slug={workspace.slug} base={base} onOpen={() => openChat()} />
            <div className="sidebar-section">
              <p className="sidebar-section-label">System</p>
              <SidebarApprovals slug={workspace.slug} base={base} />
              <NavLink to={`${base}/integrations`}>Integrations</NavLink>
              <NavLink to={`${base}/usage`}>Usage</NavLink>
              <NavLink to={`${base}/debug`} end>
                Diagnostics
              </NavLink>
              <NavLink to={`${base}/debug/llm`}>LLM Inspector</NavLink>
              <NavLink to={`${base}/settings`}>Settings</NavLink>
            </div>
          </nav>
        ) : null}

        {user ? <div className="user-line">{user.name || user.email}</div> : null}
      </aside>
      <main className="main">
        <Outlet context={{ openChat } satisfies LayoutOutletContext} />
      </main>
      {workspace && !chatModal && !onDevs ? <HrChatLauncher /> : null}
      {workspace && chatModal ? (
        <ChatModal initialHandle={chatModal.handle} onClose={closeChat} />
      ) : null}
    </div>
  );

  // Wrap in the realtime provider once a workspace is known so the sidebar and
  // page content share a single SSE connection.
  return workspace ? (
    <WorkspaceEventsProvider slug={workspace.slug}>{layout}</WorkspaceEventsProvider>
  ) : (
    layout
  );
}
