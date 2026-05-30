import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";

export function DebugPage() {
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [events, setEvents] = useState<Record<string, unknown>[]>([]);
  const [turns, setTurns] = useState<Record<string, unknown>[]>([]);
  const [audit, setAudit] = useState<Record<string, unknown>[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function refresh() {
    if (!slug) return;
    setError(null);
    const [eventRows, turnRows, auditRows] = await Promise.all([
      api.listEvents(slug),
      api.listTurns(slug),
      api.listAudit(slug),
    ]);
    setEvents(eventRows);
    setTurns(turnRows);
    setAudit(auditRows);
  }

  useEffect(() => {
    void refresh().catch((err: Error) => setError(err.message));
  }, [slug]);

  async function handleInject() {
    if (!slug) return;
    setMessage(null);
    try {
      const result = await api.injectEvent(slug, "Diagnostics test event");
      setMessage(`Injected event ${result.event_id}`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Inject failed");
    }
  }

  async function handleRunOnce() {
    if (!slug) return;
    setMessage(null);
    try {
      const result = await api.runOnce(slug);
      setMessage(`Processed ${result.processed} event(s)`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Run failed");
    }
  }

  return (
    <div className="stack">
      {error ? <div className="error">{error}</div> : null}
      {message ? <div className="success">{message}</div> : null}

      <div className="row">
        <button type="button" onClick={() => void handleInject()}>
          Inject test event
        </button>
        <button type="button" onClick={() => void handleRunOnce()}>
          Run once
        </button>
        <button type="button" className="secondary" onClick={() => void refresh()}>
          Refresh
        </button>
      </div>

      <section className="panel">
        <h3>Events</h3>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Trigger</th>
              <th>Status</th>
              <th>Received</th>
            </tr>
          </thead>
          <tbody>
            {events.map((row) => (
              <tr key={String(row.id)}>
                <td>{String(row.id).slice(0, 8)}…</td>
                <td>{String(row.trigger_type)}</td>
                <td>{String(row.processing_status)}</td>
                <td>{String(row.received_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h3>Turns</h3>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Status</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {turns.map((row) => (
              <tr key={String(row.id)}>
                <td>{String(row.id).slice(0, 8)}…</td>
                <td>{String(row.current_status)}</td>
                <td>{String(row.started_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h3>Audit log</h3>
        <table>
          <thead>
            <tr>
              <th>Action</th>
              <th>Outcome</th>
              <th>Policy</th>
              <th>At</th>
            </tr>
          </thead>
          <tbody>
            {audit.map((row) => (
              <tr key={String(row.id)}>
                <td>{String(row.action_type)}</td>
                <td>{String(row.outcome)}</td>
                <td>{String(row.policy_decision)}</td>
                <td>{String(row.occurred_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
