import { NavLink, Outlet } from "react-router-dom";
import { useApp } from "../context/AppContext";

type LayoutProps = {
  title?: string;
  showNav?: boolean;
};

export function Layout({ title = "Pidgin", showNav = true }: LayoutProps) {
  const { workspace, user } = useApp();

  return (
    <div className="layout">
      <aside className="sidebar">
        <div>
          <h1>Pidgin</h1>
          <div className="muted">{workspace?.display_name ?? "AI workforce"}</div>
          {user ? <div className="muted user-line">{user.name || user.email}</div> : null}
        </div>
        {showNav && workspace ? (
          <nav>
            <NavLink to="" end>
              Team
            </NavLink>
            <NavLink to="hire">Hire a role</NavLink>
            <NavLink to="templates">Your templates</NavLink>
            <NavLink to="debug">Diagnostics</NavLink>
          </nav>
        ) : null}
      </aside>
      <main className="main">
        <h2 style={{ marginTop: 0 }}>{title}</h2>
        <Outlet />
      </main>
    </div>
  );
}
