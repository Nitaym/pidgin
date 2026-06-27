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
    tagline: "Let agents read files you grant access to",
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
          { label: "Google Cloud console", href: "https://console.cloud.google.com/projectcreate" },
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
        text: "Create a service account, then add a JSON key and download it.",
        links: [
          {
            label: "Service accounts",
            href: "https://console.cloud.google.com/iam-admin/serviceaccounts",
          },
        ],
      },
      {
        text:
          "To read a whole organisation's files, enable domain-wide delegation and authorise the scope " +
          "https://www.googleapis.com/auth/drive.readonly in the Admin console, then set “Delegated user " +
          "email” below to the user whose files agents should see.",
        links: [
          {
            label: "Domain-wide delegation",
            href: "https://admin.google.com/ac/owl/domainwidedelegation",
          },
        ],
      },
      {
        text:
          "For a single file or folder instead, share it with the service account's email address and leave " +
          "“Delegated user email” blank.",
      },
      {
        text:
          "Paste the JSON key file's contents into “Service account JSON” below and save the connection.",
      },
    ],
    docs: {
      label: "Google: service accounts & delegation",
      href: "https://developers.google.com/identity/protocols/oauth2/service-account",
    },
  },
};

export function integrationSetupGuide(connectorType: string): SetupGuide | null {
  return SETUP_GUIDES[connectorType] ?? null;
}

export function formatCapability(cap: string): string {
  return cap.replace(/_/g, " ");
}
