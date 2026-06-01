import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { Layout } from "./components/Layout";
import { useApp } from "./context/AppContext";
import { AgentProfilePage } from "./pages/AgentProfilePage";
import { ChatPage } from "./pages/ChatPage";
import { DebugPage } from "./pages/DebugPage";
import { HireWizardPage } from "./pages/HireWizardPage";
import { LoginPage } from "./pages/LoginPage";
import { TeamPage } from "./pages/TeamPage";
import { TemplateEditorPage, TemplatesPage } from "./pages/TemplatesPage";
import { WelcomePage } from "./pages/WelcomePage";

function RootRedirect() {
  const { loading, user, workspace } = useApp();

  if (loading) {
    return (
      <div className="auth-screen">
        <p className="muted">Loading…</p>
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  if (!workspace) {
    return <Navigate to="/welcome" replace />;
  }
  return <Navigate to={`/${workspace.slug}/`} replace />;
}

function WorkspaceApp() {
  const { workspaceSlug = "" } = useParams();
  const { loading, user, workspace } = useApp();

  if (loading) {
    return (
      <div className="auth-screen">
        <p className="muted">Loading…</p>
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  if (!workspace) {
    return <Navigate to="/welcome" replace />;
  }
  if (workspace.slug !== workspaceSlug) {
    return <Navigate to={`/${workspace.slug}/`} replace />;
  }

  return (
    <Routes>
      <Route element={<Layout title="Team" />}>
        <Route index element={<TeamPage />} />
        <Route path="hire" element={<HireWizardPage />} />
        <Route path="templates" element={<TemplatesPage />} />
        <Route path="templates/:templateSlug" element={<TemplateEditorPage />} />
        <Route path="agents/:handle" element={<AgentProfilePage />} />
      </Route>
      <Route element={<Layout title="Chat" />}>
        <Route path="rooms/:roomId/chat" element={<ChatPage />} />
      </Route>
      <Route element={<Layout title="Diagnostics" />}>
        <Route path="debug" element={<DebugPage />} />
      </Route>
      <Route path="*" element={<Navigate to="" replace />} />
    </Routes>
  );
}

export default function App() {
  const { loading, user, workspace } = useApp();

  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route
        path="/login"
        element={
          !loading && user ? (
            workspace ? (
              <Navigate to={`/${workspace.slug}/`} replace />
            ) : (
              <Navigate to="/welcome" replace />
            )
          ) : (
            <LoginPage />
          )
        }
      />
      <Route
        path="/welcome"
        element={
          loading ? (
            <div className="auth-screen">
              <p className="muted">Loading…</p>
            </div>
          ) : !user ? (
            <Navigate to="/login" replace />
          ) : workspace ? (
            <Navigate to={`/${workspace.slug}/`} replace />
          ) : (
            <WelcomePage />
          )
        }
      />
      <Route path="/:workspaceSlug/*" element={<WorkspaceApp />} />
    </Routes>
  );
}
