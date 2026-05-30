const API_BASE = "";

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
    ...options,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string | unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail)) {
        detail = JSON.stringify(body.detail);
      }
    } catch {
      /* ignore */
    }
    throw new Error(detail || `Request failed (${response.status})`);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export type User = {
  sub: string;
  email: string;
  name: string;
  picture: string;
};

export type Workspace = {
  id: string;
  slug: string;
  display_name: string;
  path: string;
};

export type Bootstrap = {
  user: User | null;
  workspace: Workspace | null;
};

export type AuthConfig = {
  google_enabled: boolean;
  dev_login_enabled: boolean;
};

export type Agent = {
  id: string;
  display_name: string;
  role_title: string;
  handle: string;
  current_status: string;
  created_at: string;
};

export type Room = { id: string; name: string; purpose: string | null; modality: string };

export type Message = {
  id: string;
  sender_display_name: string;
  body_text: string;
  created_at: string;
  originating_turn_id: string | null;
};

function workspaceBase(slug: string) {
  return `/${slug}/api`;
}

export const api = {
  bootstrap: () => request<Bootstrap>("/api/bootstrap"),
  authConfig: () => request<AuthConfig>("/api/auth/config"),
  devLogin: (email = "dev@pidgin.local", name = "Dev User") =>
    request<{ status: string }>("/api/auth/dev-login", {
      method: "POST",
      body: JSON.stringify({ email, name }),
    }),
  logout: () =>
    request<{ status: string }>("/api/auth/logout", {
      method: "POST",
    }),
  createWorkspace: (name: string, slug: string) =>
    request<Workspace>("/api/workspace", {
      method: "POST",
      body: JSON.stringify({ name, slug }),
    }),
  listAgents: (slug: string) => request<Agent[]>(`${workspaceBase(slug)}/agents`),
  listRooms: (slug: string) => request<Room[]>(`${workspaceBase(slug)}/rooms`),
  hireSupport: (slug: string) =>
    request<{ room_id: string; room_name: string; display_name: string }>(
      `${workspaceBase(slug)}/hire`,
      { method: "POST" },
    ),
  getRoomMessages: (slug: string, roomId: string) =>
    request<{ conversation_id: string; messages: Message[] }>(
      `${workspaceBase(slug)}/rooms/${roomId}/messages`,
    ),
  sendRoomMessage: (slug: string, roomId: string, body: string) =>
    request<{ messages: Message[] }>(`${workspaceBase(slug)}/rooms/${roomId}/messages`, {
      method: "POST",
      body: JSON.stringify({ body }),
    }),
  injectEvent: (slug: string, message: string) =>
    request<{ event_id: string }>(`${workspaceBase(slug)}/inject-event`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  runOnce: (slug: string) =>
    request<{ processed: number }>(`${workspaceBase(slug)}/run-once`, {
      method: "POST",
    }),
  listEvents: (slug: string) =>
    request<Record<string, unknown>[]>(`${workspaceBase(slug)}/events`),
  listTurns: (slug: string) =>
    request<Record<string, unknown>[]>(`${workspaceBase(slug)}/turns`),
  listAudit: (slug: string) =>
    request<Record<string, unknown>[]>(`${workspaceBase(slug)}/audit`),
};

export function googleLoginUrl() {
  return "/api/auth/google/login";
}
