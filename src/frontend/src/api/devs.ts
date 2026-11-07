// Devs page API: interactive Claude Code terminals (src/pidgin/api/routes/devterm_api.py).

export type Dev = {
  id: string;
  name: string;
  cwd: string;
  session_id: string;
  status: "idle" | "running" | "exited";
};

async function call<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers ?? {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

const base = (slug: string) => `/${slug}/api/devs`;

export const devsApi = {
  list: (slug: string) => call<{ devs: Dev[]; default_cwd: string }>(base(slug)),
  add: (slug: string, body: { name?: string; cwd?: string }) =>
    call<Dev>(base(slug), { method: "POST", body: JSON.stringify(body) }),
  patch: (slug: string, id: string, body: { name?: string; cwd?: string }) =>
    call<Dev>(`${base(slug)}/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  remove: (slug: string, id: string) => call<{ status: string }>(`${base(slug)}/${id}`, { method: "DELETE" }),
  restart: (slug: string, id: string) => call<Dev>(`${base(slug)}/${id}/restart`, { method: "POST" }),
  wsUrl: (slug: string, id: string, cols: number, rows: number) => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}${base(slug)}/${id}/ws?cols=${cols}&rows=${rows}`;
  },
};
