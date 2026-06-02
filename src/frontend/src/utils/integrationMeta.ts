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

export function formatCapability(cap: string): string {
  return cap.replace(/_/g, " ");
}
