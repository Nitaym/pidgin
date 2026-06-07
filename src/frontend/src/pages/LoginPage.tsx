import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, googleLoginUrl } from "../api/client";

export function LoginPage() {
  const [searchParams] = useSearchParams();
  const [googleEnabled, setGoogleEnabled] = useState(false);
  const [devEnabled, setDevEnabled] = useState(false);
  const [backendDown, setBackendDown] = useState(false);
  const [error, setError] = useState<string | null>(
    searchParams.get("error") ? "Google sign-in was cancelled or failed." : null,
  );

  useEffect(() => {
    api
      .authConfig()
      .then((config) => {
        setGoogleEnabled(config.google_enabled);
        setDevEnabled(config.dev_login_enabled);
      })
      .catch(() => setBackendDown(true));
  }, []);

  async function handleDevLogin() {
    setError(null);
    try {
      await api.devLogin();
      window.location.href = "/";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dev login failed");
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-card panel stack">
        <h1 style={{ margin: 0 }}>Welcome to Pidgin</h1>
        <p className="muted">
          Sign in to set up your AI workforce workspace and hire your first agents.
        </p>

        {error ? <div className="error">{error}</div> : null}

        {backendDown ? (
          <div className="error" style={{ textAlign: "center" }}>
            <strong>Backend is not running.</strong>
            <br />
            <span style={{ fontSize: 13 }}>Start the server and refresh the page.</span>
          </div>
        ) : googleEnabled ? (
          <a className="btn google" href={googleLoginUrl()}>
            Continue with Google
          </a>
        ) : (
          <p className="muted">
            Set <code>GOOGLE_CLIENT_ID</code> and <code>GOOGLE_CLIENT_SECRET</code> on the
            server to enable Google login.
          </p>
        )}

        {devEnabled ? (
          <button type="button" className="secondary" onClick={() => void handleDevLogin()}>
            Dev sign-in (local only)
          </button>
        ) : null}
      </div>
    </div>
  );
}
