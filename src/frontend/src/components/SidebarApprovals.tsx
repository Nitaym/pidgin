import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api/client";

type SidebarApprovalsProps = {
  slug: string;
  base: string;
};

export function SidebarApprovals({ slug, base }: SidebarApprovalsProps) {
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    const refresh = () => {
      void api
        .listApprovals(slug)
        .then((list) => {
          if (!cancelled) setCount(list.length);
        })
        .catch(() => {
          if (!cancelled) setCount(0);
        });
    };
    refresh();
    const interval = setInterval(refresh, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [slug]);

  return (
    <NavLink to={`${base}/approvals`}>
      Approvals
      {count > 0 && <span className="sidebar-chat-badge">{count}</span>}
    </NavLink>
  );
}
