import { useCallback, useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api/client";
import { useWorkspaceEvent } from "../context/WorkspaceEvents";

type SidebarApprovalsProps = {
  slug: string;
  base: string;
};

export function SidebarApprovals({ slug, base }: SidebarApprovalsProps) {
  const [count, setCount] = useState(0);

  const refresh = useCallback(() => {
    if (!slug) return;
    void api
      .listApprovals(slug)
      .then((list) => setCount(list.length))
      .catch(() => setCount(0));
  }, [slug]);

  // Approvals push `approval.created` / `approval.resolved` so the badge stays
  // live; the slow interval is a safety net if the SSE stream drops.
  useWorkspaceEvent("approval.*", refresh);
  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 60000);
    return () => clearInterval(interval);
  }, [refresh]);

  return (
    <NavLink to={`${base}/approvals`}>
      Approvals
      {count > 0 && <span className="sidebar-chat-badge">{count}</span>}
    </NavLink>
  );
}
