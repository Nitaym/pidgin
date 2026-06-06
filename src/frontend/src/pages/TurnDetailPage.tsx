import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";

export function TurnDetailPage() {
  const { turnId = "" } = useParams();
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      if (!slug || !turnId) return;
      setError(null);
      try {
        const data = await api.getTurn(slug, turnId);
        setDetail(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load turn");
      }
    }
    void load();
  }, [slug, turnId]);

  if (error) {
    return <div className="error">{error}</div>;
  }
  if (!detail) {
    return <p className="muted">Loading turn…</p>;
  }

  const invocations = (detail.model_invocations as Record<string, unknown>[]) ?? [];
  const audit = (detail.audit as Record<string, unknown>[]) ?? [];

  return (
    <div className="stack">
      <p className="muted">
        <Link to="../debug">← Debug</Link>
      </p>
      <h2>Turn {turnId}</h2>
      <section className="panel stack">
        <h3>Model invocations ({invocations.length})</h3>
        {invocations.length === 0 ? (
          <p className="muted">None</p>
        ) : (
          invocations.map((row) => (
            <pre key={String(row.id)} className="code-block">
              {JSON.stringify(row, null, 2)}
            </pre>
          ))
        )}
      </section>
      <section className="panel stack">
        <h3>Gate audit ({audit.length})</h3>
        {audit.length === 0 ? (
          <p className="muted">None</p>
        ) : (
          audit.map((row) => (
            <div key={String(row.id)} className="message">
              <div className="meta">
                {String(row.action_type)} · {String(row.outcome)} ·{" "}
                {String(row.policy_decision)}
              </div>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
