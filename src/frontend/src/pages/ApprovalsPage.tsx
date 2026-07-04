import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api, type Agent, type ApprovalContext, type PendingApproval } from "../api/client";
import { useApp } from "../context/AppContext";
import { ChatView } from "../components/ChatView";

function describeAction(approval: PendingApproval): string {
  let params: Record<string, unknown> = {};
  try {
    params = JSON.parse(approval.proposed_action_params_json) as Record<string, unknown>;
  } catch {
    /* leave empty */
  }
  if (approval.proposed_action === "plan") {
    const actions = Array.isArray(params.actions) ? params.actions : [];
    const n = actions.length;
    return n === 1 ? "1 step staged for your approval" : `${n} steps staged for your approval`;
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

// The "why" + discussion, lazy-loaded when the owner expands an approval.
function ApprovalDetail({
  slug,
  approval,
  agent,
}: {
  slug: string;
  approval: PendingApproval;
  agent: Agent | undefined;
}) {
  const [context, setContext] = useState<ApprovalContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showChat, setShowChat] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .getApprovalContext(slug, approval.id)
      .then((ctx) => alive && setContext(ctx))
      .catch((err: Error) => alive && setError(err.message));
    return () => {
      alive = false;
    };
  }, [slug, approval.id]);

  if (error) return <div className="error" style={{ marginTop: 8 }}>{error}</div>;
  if (!context) return <p className="muted" style={{ marginTop: 8 }}>Loading context…</p>;

  const { why, steps } = context;
  const handle = agent?.handle ?? context.agent.handle;
  const displayName = agent?.display_name ?? context.agent.display_name;

  return (
    <div className="stack" style={{ gap: 12, marginTop: 4 }}>
      <div className="approval-why">
        <p className="eyebrow" style={{ margin: "0 0 4px" }}>
          What {displayName} is working on
        </p>
        <p style={{ margin: 0 }}>{why.trigger.summary}</p>
      </div>

      {why.rationale ? (
        <div className="approval-why">
          <p className="eyebrow" style={{ margin: "0 0 4px" }}>
            Why {displayName} wants this
          </p>
          <div className="approval-rationale">
            <ReactMarkdown>{why.rationale}</ReactMarkdown>
          </div>
        </div>
      ) : null}

      <div className="approval-why">
        <p className="eyebrow" style={{ margin: "0 0 6px" }}>
          {steps.length === 1 ? "What it will do" : `What it will do (${steps.length} steps)`}
        </p>
        <ol className="approval-steps">
          {steps.map((step) => (
            <li key={step.index}>
              <span className="approval-step-kind">{step.action_type}</span> {step.summary}
            </li>
          ))}
        </ol>
      </div>

      <p className="muted field-hint" style={{ margin: 0 }}>
        Needs your sign-off: {why.policy_reason}
      </p>

      <div>
        <button
          type="button"
          className="secondary"
          style={{ padding: "4px 12px", fontSize: 13 }}
          onClick={() => setShowChat((v) => !v)}
        >
          {showChat ? "Hide conversation" : `💬 Discuss with ${displayName}`}
        </button>
        <p className="muted field-hint" style={{ margin: "6px 0 0" }}>
          Ask why it needs this before you decide — it answers in its own thread, and the
          request stays pending until you approve or reject.
        </p>
        {showChat ? (
          <div className="approval-chat-embed">
            <ChatView
              key={handle}
              slug={slug}
              agentHandle={handle}
              agentDisplayName={displayName}
              backLink={undefined}
              inModal
              compact
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ApprovalsPage() {
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

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
            const isOpen = expanded === approval.id;
            return (
              <div key={approval.id} className="panel stack" style={{ gap: 8 }}>
                <div className="page-header" style={{ margin: 0 }}>
                  <div>
                    <p className="muted" style={{ margin: 0 }}>
                      {agent ? `${agent.display_name} · @${agent.handle}` : approval.ai_employee_id}
                    </p>
                    <p style={{ margin: "4px 0 0" }}>{describeAction(approval)}</p>
                  </div>
                  <button
                    type="button"
                    className="secondary"
                    style={{ padding: "4px 12px", fontSize: 13 }}
                    onClick={() => setExpanded(isOpen ? null : approval.id)}
                    aria-expanded={isOpen}
                  >
                    {isOpen ? "Hide details" : "Why & discuss"}
                  </button>
                </div>

                {isOpen ? (
                  <ApprovalDetail slug={slug} approval={approval} agent={agent} />
                ) : null}

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
