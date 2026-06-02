import type { IntegrationMeta } from "../utils/integrationMeta";

type IntegrationBrandProps = {
  meta: IntegrationMeta;
  name: string;
  size?: "sm" | "lg";
};

export function IntegrationBrand({ meta, name, size = "sm" }: IntegrationBrandProps) {
  return (
    <div className={`integration-brand integration-brand-${size}`}>
      <span
        className="integration-monogram"
        style={{ background: meta.accent }}
        aria-hidden="true"
      >
        {meta.monogram}
      </span>
      <div>
        <strong>{name}</strong>
        {size === "lg" ? <p className="muted integration-tagline">{meta.tagline}</p> : null}
      </div>
    </div>
  );
}
