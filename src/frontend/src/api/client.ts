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

export type HireCustomization = import("../types/hire").HireCustomization;

export type RoleTemplatesResponse = {
  bundled: Array<{
    source: "bundled";
    template_id: string;
    name: string;
    role_title: string;
    version: string;
    description: string;
  }>;
  workspace: Array<{
    source: "workspace";
    slug: string;
    name: string;
    current_version: number;
    updated_at: string;
  }>;
};

export type WorkspaceTemplateDetail = {
  source: "workspace";
  slug: string;
  name: string;
  version: number;
  current_version: number;
  updated_at: string;
  lineage?: Record<string, string>;
  customization: HireCustomization;
};

export type BundledTemplateDetail = {
  source: "bundled";
  template_id: string;
  name: string;
  version: string;
  default_job_requirements: HireCustomization["job_requirements"];
  default_ideal_candidate: HireCustomization["ideal_candidate"];
};

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
  listRoleTemplates: (slug: string) =>
    request<RoleTemplatesResponse>(`${workspaceBase(slug)}/role-templates`),
  getBundledTemplate: (slug: string, templateId: string) =>
    request<BundledTemplateDetail>(
      `${workspaceBase(slug)}/role-templates/bundled/${templateId}`,
    ),
  getWorkspaceTemplate: (slug: string, templateSlug: string) =>
    request<WorkspaceTemplateDetail>(
      `${workspaceBase(slug)}/role-templates/workspace/${templateSlug}`,
    ),
  createWorkspaceTemplate: (
    slug: string,
    body: {
      name: string;
      slug?: string;
      duplicate_from_recipe_id?: string;
      customization?: HireCustomization;
    },
  ) =>
    request<WorkspaceTemplateDetail>(`${workspaceBase(slug)}/role-templates/workspace`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  saveWorkspaceTemplate: (
    slug: string,
    templateSlug: string,
    body: { name?: string; customization: HireCustomization },
  ) =>
    request<WorkspaceTemplateDetail>(
      `${workspaceBase(slug)}/role-templates/workspace/${templateSlug}`,
      { method: "PATCH", body: JSON.stringify(body) },
    ),
  deleteWorkspaceTemplate: (slug: string, templateSlug: string) =>
    request<{ deleted: string }>(
      `${workspaceBase(slug)}/role-templates/workspace/${templateSlug}`,
      { method: "DELETE" },
    ),
  hireAgent: (
    slug: string,
    body: {
      template_source: "bundled" | "workspace";
      template_id?: string;
      slug?: string;
      customization: HireCustomization;
      display_name: string;
      handle?: string;
    },
  ) =>
    request<{ room_id: string; room_name: string; handle: string; display_name: string }>(
      `${workspaceBase(slug)}/hire`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  hireSupport: (slug: string) =>
    request<{ room_id: string; room_name: string; display_name: string }>(
      `${workspaceBase(slug)}/hire`,
      { method: "POST" },
    ),
  getAgentBrief: (slug: string, handle: string) =>
    request<{ handle: string; customization: HireCustomization | null }>(
      `${workspaceBase(slug)}/agents/${handle}/brief`,
    ),
  patchAgentBrief: (slug: string, handle: string, customization: HireCustomization) =>
    request<{ handle: string; customization: HireCustomization }>(
      `${workspaceBase(slug)}/agents/${handle}/brief`,
      { method: "PATCH", body: JSON.stringify(customization) },
    ),
  createTemplateFromAgent: (
    slug: string,
    handle: string,
    body: { name: string; slug?: string },
  ) =>
    request<WorkspaceTemplateDetail>(
      `${workspaceBase(slug)}/agents/${handle}/create-template`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  createHrAssistSession: (
    slug: string,
    contextType: "hire" | "agent" | "template",
    contextId: string,
  ) =>
    request<{ session_id: string; messages: unknown[] }>(
      `${workspaceBase(slug)}/hr-assist/sessions`,
      {
        method: "POST",
        body: JSON.stringify({ context_type: contextType, context_id: contextId }),
      },
    ),
  sendHrAssistMessage: (slug: string, sessionId: string, bodyText: string) =>
    request<{
      operator_message: unknown;
      assist_message: unknown;
      suggestion?: unknown;
    }>(`${workspaceBase(slug)}/hr-assist/sessions/${sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ body_text: bodyText }),
    }),
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
