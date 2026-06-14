export type JobRequirements = {
  mission: string;
  responsibilities: string[];
  out_of_scope: string[];
};

export type IdealCandidate = {
  tone: string;
  decision_framework: string;
  escalation_rules: string;
};

export type HireCustomization = {
  job_requirements: JobRequirements;
  ideal_candidate: IdealCandidate;
  your_take: string;
  /** "" (unspecified), "female", or "male" */
  gender?: "" | "female" | "male";
  /** Voice preset key (see utils/voicePresets); "" → auto-pick by gender */
  voice?: string;
};

export const emptyCustomization = (): HireCustomization => ({
  job_requirements: { mission: "", responsibilities: [], out_of_scope: [] },
  ideal_candidate: { tone: "", decision_framework: "", escalation_rules: "" },
  your_take: "",
  gender: "",
  voice: "",
});

export type TemplateSummary = {
  source: "bundled" | "workspace";
  template_id?: string;
  slug?: string;
  name: string;
  role_title?: string;
  version?: string;
  current_version?: number;
  updated_at?: string;
  description?: string;
};

export type SelectedTemplate =
  | { source: "bundled"; templateId: string; name: string; version: string }
  | { source: "workspace"; slug: string; name: string; version: number }
  | { source: "blank"; name: string };

export type HrAssistMessage = {
  id: string;
  role: "operator" | "assist";
  body_text: string;
  created_at: string;
  suggestion?: {
    action: "apply" | "append_your_take";
    targets: Record<string, string>;
  };
};
