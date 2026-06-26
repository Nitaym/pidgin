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
  conversation_id?: string | null;
  is_preseeded?: boolean;
  preseeded_blurb?: string | null;
};

export type HireCustomization = import("../types/hire").HireCustomization;

export type BundledTemplateSummary = {
  source: "bundled";
  template_id: string;
  name: string;
  role_title: string;
  version: string;
  description: string;
  archived: boolean;
};

export type WorkspaceTemplateSummary = {
  source: "workspace";
  slug: string;
  name: string;
  current_version: number;
  updated_at: string;
  archived: boolean;
};

export type RoleTemplatesResponse = {
  bundled: BundledTemplateSummary[];
  workspace: WorkspaceTemplateSummary[];
};

export type CandidateFinderTurn = { role: "operator" | "assist"; text: string };

export type CandidateFinderResponse = {
  reply: string;
  recommended: string[];
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

export type TemplatePermissions = {
  can_read: string[];
  can_write: string[];
  requires_approval: string[];
  blocked: string[];
};

export type BundledTemplateDetail = {
  source: "bundled";
  template_id: string;
  name: string;
  role_title: string;
  version: string;
  description: string;
  default_channels: string[];
  permissions: TemplatePermissions;
  default_job_requirements: HireCustomization["job_requirements"];
  default_ideal_candidate: HireCustomization["ideal_candidate"];
  archived: boolean;
};

export type Message = {
  id: string;
  sender_display_name: string;
  body_text: string;
  created_at: string;
  originating_turn_id: string | null;
};

export type IntegrationCatalogEntry = {
  connector_type: string;
  name: string;
  description: string;
  auth_modes: string[];
  builtin?: boolean;
  capabilities: string[];
  oauth_scopes?: string[];
  manual_fields?: Array<{ key: string; label: string; secret: boolean }>;
};

export type IntegrationInstallation = {
  id: string;
  connector_type: string;
  display_name: string;
  status: string;
  catalog_name?: string;
  config_json?: Record<string, unknown>;
  installed_at: string;
  updated_at: string;
  last_health_check_at?: string | null;
};

export type LlmChatMessage = {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  tool_call_id?: string | null;
  name?: string | null;
};

export type LlmToolSpec = {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
};

export type LlmResponse = {
  assistant_text?: string | null;
  actions?: Array<{ action_type: string; params: Record<string, unknown> }>;
  stop_reason?: string;
  usage?: { input_tokens: number; output_tokens: number };
  raw_response?: Record<string, unknown>;
  error_text?: string | null;
};

export type LlmInvocation = {
  id: string;
  turn_id: string;
  sequence_in_turn: number;
  provider: string;
  model_id: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd_micros: number | null;
  latency_ms: number | null;
  error_text: string | null;
  invoked_at: string;
  ai_employee_id: string | null;
  conversation_id: string | null;
  turn_status: string | null;
  trigger_type: string | null;
  agent_display_name: string | null;
  agent_handle: string | null;
  source: string;
  request_messages: LlmChatMessage[];
  request_tools: LlmToolSpec[];
  response: LlmResponse | null;
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
  getHrAgent: (slug: string) =>
    request<{ handle: string; display_name: string }>(`${workspaceBase(slug)}/hr-agent`),
  getAgent: (slug: string, handle: string) =>
    request<Agent>(`${workspaceBase(slug)}/agents/${handle}`),
  getAgentConversation: (slug: string, handle: string) =>
    request<{ id: string; ai_employee_id: string; modality: string }>(
      `${workspaceBase(slug)}/agents/${handle}/conversation`,
    ),
  listRoleTemplates: (slug: string) =>
    request<RoleTemplatesResponse>(`${workspaceBase(slug)}/role-templates`),
  archiveProfile: (
    slug: string,
    source: "bundled" | "workspace",
    id: string,
    archived: boolean,
  ) =>
    request<{ source: string; id: string; archived: boolean }>(
      `${workspaceBase(slug)}/role-templates/archive`,
      {
        method: "POST",
        body: JSON.stringify({ source, id, archived }),
      },
    ),
  findCandidate: (slug: string, message: string, history: CandidateFinderTurn[]) =>
    request<CandidateFinderResponse>(`${workspaceBase(slug)}/role-templates/assist`, {
      method: "POST",
      body: JSON.stringify({ message, history }),
    }),
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
    request<{ conversation_id: string; handle: string; display_name: string }>(
      `${workspaceBase(slug)}/hire`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  hireSupport: (slug: string) =>
    request<{ conversation_id: string; display_name: string }>(
      `${workspaceBase(slug)}/hire`,
      { method: "POST" },
    ),
  getAgentBrief: (slug: string, handle: string) =>
    request<
      Partial<Agent> & { handle: string; customization: HireCustomization | null }
    >(`${workspaceBase(slug)}/agents/${handle}/brief`),
  patchAgentBrief: (slug: string, handle: string, customization: HireCustomization) =>
    request<{ handle: string; customization: HireCustomization }>(
      `${workspaceBase(slug)}/agents/${handle}/brief`,
      { method: "PATCH", body: JSON.stringify(customization) },
    ),
  archiveAgent: (slug: string, handle: string) =>
    request<{ handle: string; current_status: string }>(
      `${workspaceBase(slug)}/agents/${handle}/archive`,
      { method: "POST" },
    ),
  activateAgent: (slug: string, handle: string) =>
    request<{ handle: string; current_status: string }>(
      `${workspaceBase(slug)}/agents/${handle}/activate`,
      { method: "POST" },
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
  sendHrAssistMessage: (
    slug: string,
    sessionId: string,
    bodyText: string,
    customization?: HireCustomization,
  ) =>
    request<{
      operator_message: unknown;
      assist_message: unknown;
      suggestion?: unknown;
    }>(`${workspaceBase(slug)}/hr-assist/sessions/${sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ body_text: bodyText, customization }),
    }),
  getAgentMessages: (slug: string, handle: string) =>
    request<{ conversation_id: string; messages: Message[] }>(
      `${workspaceBase(slug)}/agents/${handle}/messages`,
    ),
  sendAgentMessage: (
    slug: string,
    handle: string,
    body: string,
    stream = false,
  ) =>
    request<{
      messages?: Message[];
      message_id: string;
      event_id: string;
      conversation_id: string;
      stream_url?: string;
    }>(`${workspaceBase(slug)}/agents/${handle}/messages?stream=${stream ? "true" : "false"}`, {
      method: "POST",
      body: JSON.stringify({ body }),
    }),
  getTurn: (slug: string, turnId: string) =>
    request<Record<string, unknown>>(`${workspaceBase(slug)}/turns/${turnId}`),
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
  listLlmInvocations: (slug: string, opts: { limit?: number; after?: string } = {}) => {
    const params = new URLSearchParams();
    if (opts.limit) params.set("limit", String(opts.limit));
    if (opts.after) params.set("after", opts.after);
    const query = params.toString();
    return request<LlmInvocation[]>(
      `${workspaceBase(slug)}/llm-invocations${query ? `?${query}` : ""}`,
    );
  },
  getIntegrationsCatalog: (slug: string) =>
    request<IntegrationCatalogEntry[]>(`${workspaceBase(slug)}/integrations/catalog`),
  listIntegrations: (slug: string) =>
    request<IntegrationInstallation[]>(`${workspaceBase(slug)}/integrations`),
  connectIntegrationManual: (
    slug: string,
    connectorType: string,
    body: { display_name: string; fields: Record<string, string> },
  ) =>
    request<IntegrationInstallation>(
      `${workspaceBase(slug)}/integrations/${connectorType}/manual`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  startIntegrationOAuth: (slug: string, connectorType: string) =>
    request<{ authorization_url: string }>(
      `${workspaceBase(slug)}/integrations/${connectorType}/oauth/start`,
      { method: "POST", body: JSON.stringify({}) },
    ),
  checkIntegrationHealth: (slug: string, installationId: string) =>
    request<{ ok: boolean; message: string }>(
      `${workspaceBase(slug)}/integrations/${installationId}/health`,
      { method: "POST" },
    ),
  disconnectIntegration: (slug: string, installationId: string) =>
    request<{ deleted: string }>(`${workspaceBase(slug)}/integrations/${installationId}`, {
      method: "DELETE",
    }),
  updateIntegrationConfig: (
    slug: string,
    installationId: string,
    config: Record<string, string>,
  ) =>
    request<IntegrationInstallation>(
      `${workspaceBase(slug)}/integrations/${installationId}/config`,
      { method: "PATCH", body: JSON.stringify({ config }) },
    ),
};

export function googleLoginUrl() {
  return "/api/auth/google/login";
}
