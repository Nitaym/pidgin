import { useCallback, useEffect, useState } from "react";
import { api, type Agent, type PendingApproval } from "../api/client";
import { useApp } from "../context/AppContext";

function describeAction(approval: PendingApproval): string {
  let params: Record<string, unknown> = {};
  try {
    params = JSON.parse(approval.proposed_action_params_json) as Record<string, unknown>;
  } catch {
    /* leave empty */
  }
  if (approval.proposed_action === "execute") {
    const kind = (params.kind as string) || "file";
    const name = (params.name as string) || "(unnamed)";
    const target = (params.resource_uri as string) || "?";
    return `create ${kind} "${name}" in ${target}`;
  }
  const rest = Object.entries(params)
    .map(([k, v]) => `${k}: ${String(v)}`)
    .join(", ");
  return rest ? `${approval.proposed_action} — ${rest}` : approval.proposed_action;
}

export function ApprovalsPage() {
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!slug) return;
    setError(null);
    const [list, agentList] = await Promise.all([
      api.listApprovals(slug),
      api.listAgents(slug),
    ]);
    setApprovals(list);
    setAgents(agentList);
  }, [slug]);

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, [load]);

  function agentFor(aiEmployeeId: string) {
    return agents.find((a) => a.id === aiEmployeeId);
  }

  async function handleApprove(id: string) {
    setPending(id);
    setError(null);
    try {
      await api.approveApproval(slug, id);
      setApprovals((prev) => prev.filter((a) => a.id !== id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(null);
    }
  }

  async function handleReject(id: string) {
    setPending(id);
    setError(null);
    try {
      await api.rejectApproval(slug, id);
      setApprovals((prev) => prev.filter((a) => a.id !== id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <p className="eyebrow" style={{ margin: "0 0 4px" }}>
            System
          </p>
          <h2>Approvals</h2>
          <p className="muted field-hint" style={{ margin: "8px 0 0" }}>
            Actions your agents have staged that need your sign-off before they happen.
          </p>
        </div>
      </div>

      {error ? <div className="error">{error}</div> : null}

      {approvals.length === 0 ? (
        <div className="empty-state">
          <h3>Nothing pending</h3>
          <p>When an agent stages an action that needs approval, it'll show up here.</p>
        </div>
      ) : (
        <div className="stack">
          {approvals.map((approval) => {
            const agent = agentFor(approval.ai_employee_id);
            return (
              <div key={approval.id} className="panel stack" style={{ gap: 8 }}>
                <div className="page-header" style={{ margin: 0 }}>
                  <div>
                    <p className="muted" style={{ margin: 0 }}>
                      {agent ? `${agent.display_name} · @${agent.handle}` : approval.ai_employee_id}
                    </p>
                    <p style={{ margin: "4px 0 0" }}>{describeAction(approval)}</p>
                  </div>
                </div>
                <div className="page-header-actions">
                  <button
                    type="button"
                    className="btn"
                    disabled={pending === approval.id}
                    onClick={() => void handleApprove(approval.id)}
                  >
                    {pending === approval.id ? "Approving…" : "Approve"}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={pending === approval.id}
                    onClick={() => void handleReject(approval.id)}
                  >
                    Reject
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
