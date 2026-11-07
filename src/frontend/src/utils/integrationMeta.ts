import type { IntegrationCatalogEntry } from "../api/client";

export type IntegrationMeta = {
  tagline: string;
  accent: string;
  monogram: string;
};

const META: Record<string, IntegrationMeta> = {
  slack: {
    tagline: "Talk to agents from your workspace",
    accent: "#611f69",
    monogram: "S",
  },
  gmail: {
    tagline: "Email routing and draft replies",
    accent: "#c5221f",
    monogram: "G",
  },
  google_drive: {
    tagline: "Read shared files, create new ones",
    accent: "#1a73e8",
    monogram: "D",
  },
  google_meet: {
    tagline: "Calendar and meeting context",
    accent: "#00897b",
    monogram: "M",
  },
  zoom: {
    tagline: "Meeting read and schedule hooks",
    accent: "#2d8cff",
    monogram: "Z",
  },
  linear: {
    tagline: "Tickets a developer picks up and reports on",
    accent: "#5e6ad2",
    monogram: "L",
  },
};

export function integrationMeta(entry: IntegrationCatalogEntry): IntegrationMeta {
  return (
    META[entry.connector_type] ?? {
      tagline: entry.description,
      accent: "var(--accent)",
      monogram: entry.name.charAt(0).toUpperCase(),
    }
  );
}

export type SetupLink = { label: string; href: string };
export type SetupStep = { text: string; links?: SetupLink[] };
export type SetupGuide = {
  title: string;
  intro?: string;
  steps: SetupStep[];
  docs?: SetupLink;
};

const SETUP_GUIDES: Record<string, SetupGuide> = {
  google_drive: {
    title: "Set up a service account",
    intro:
      "Pidgin reads Drive through a Google Cloud service account. Create one, then paste its JSON key below.",
    steps: [
      {
        text: "Create (or pick) a Google Cloud project.",
        links: [
          { label: "Google Cloud console", href: "https://console.cloud.google.com/" },
        ],
      },
      {
        text: "Enable the Google Drive API for that project.",
        links: [
          {
            label: "Enable Drive API",
            href: "https://console.cloud.google.com/apis/library/drive.googleapis.com",
          },
        ],
      },
      {
        text:
          "Create a service account — you can skip the optional “Grant access” " +
          "(permissions) and “Principals with access” steps. Then open the “⋮” menu " +
          "next to it → Manage keys → Add key → Create new key → JSON, and download " +
          "the file.",
        links: [
          {
            label: "Service accounts",
            href: "https://console.cloud.google.com/iam-admin/serviceaccounts",
          },
        ],
      },
      {
        text:
          "Paste the JSON key below. Pidgin then shows two ways to grant access — " +
          "organisation-wide or a single file/folder — using the Client ID from your key.",
      },
    ],
    docs: {
      label: "Google: service accounts & delegation",
      href: "https://developers.google.com/identity/protocols/oauth2/service-account",
    },
  },
  linear: {
    title: "Connect as the developer's own Linear member",
    intro:
      "The developer acts in Linear as its own member, so its claims, comments and hand-offs never show as you.",
    steps: [
      { text: "Invite a member for the developer to your Linear workspace (e.g. Claude, with its own email), and add it to the team it will work in." },
      {
        text: "Sign in to Linear as that member, then create a personal API key: Settings → Security & access → Personal API keys.",
        links: [{ label: "Linear API settings", href: "https://linear.app/settings/account/security" }],
      },
      { text: "Paste the key below. The health check shows who the key belongs to; it should be the developer, not you." },
      { text: "Then open the developer's Work page to pick the team, your Linear account and the repo." },
    ],
    docs: { label: "Linear: API and webhooks", href: "https://linear.app/developers" },
  },
};

export function integrationSetupGuide(connectorType: string): SetupGuide | null {
  return SETUP_GUIDES[connectorType] ?? null;
}

export function formatCapability(cap: string): string {
  return cap.replace(/_/g, " ");
}
