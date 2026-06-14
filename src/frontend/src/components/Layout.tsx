import { NavLink, Outlet, useParams } from "react-router-dom";
import { PidginLogo } from "./PidginLogo";
import { SidebarChat } from "./SidebarChat";
import { useApp } from "../context/AppContext";

type LayoutProps = {
  showNav?: boolean;
};

export function Layout({ showNav = true }: LayoutProps) {
  const { workspace, user } = useApp();
  const { workspaceSlug = workspace?.slug ?? "" } = useParams();
  const base = workspaceSlug ? `/${workspaceSlug}` : "";

  return (
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
            </div>
            <div className="sidebar-section">
              <p className="sidebar-section-label">Workforce</p>
              <NavLink to={`${base}/hire`}>Hire a role</NavLink>
              <NavLink to={`${base}/templates`}>Your templates</NavLink>
            </div>
            <SidebarChat slug={workspace.slug} base={base} />
            <div className="sidebar-section">
              <p className="sidebar-section-label">System</p>
              <NavLink to={`${base}/integrations`}>Integrations</NavLink>
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
        <Outlet />
      </main>
    </div>
  );
}
