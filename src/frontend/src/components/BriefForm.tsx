import type { HireCustomization } from "../types/hire";

type BriefFormProps = {
  value: HireCustomization;
  onChange: (next: HireCustomization) => void;
  showYourTake?: boolean;
};

function linesToList(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function listToLines(items: string[]): string {
  return items.join("\n");
}

export function BriefForm({ value, onChange, showYourTake = true }: BriefFormProps) {
  const job = value.job_requirements;
  const ideal = value.ideal_candidate;

  return (
    <div className="stack">
      <fieldset className="brief-section">
        <legend>Job requirements</legend>
        <label className="field">
          Mission
          <textarea
            rows={3}
            value={job.mission}
            onChange={(e) =>
              onChange({
                ...value,
                job_requirements: { ...job, mission: e.target.value },
              })
            }
          />
        </label>
        <label className="field">
          Responsibilities (one per line)
          <textarea
            rows={4}
            value={listToLines(job.responsibilities)}
            onChange={(e) =>
              onChange({
                ...value,
                job_requirements: {
                  ...job,
                  responsibilities: linesToList(e.target.value),
                },
              })
            }
          />
        </label>
        <label className="field">
          Out of scope (one per line)
          <textarea
            rows={3}
            value={listToLines(job.out_of_scope)}
            onChange={(e) =>
              onChange({
                ...value,
                job_requirements: {
                  ...job,
                  out_of_scope: linesToList(e.target.value),
                },
              })
            }
          />
        </label>
      </fieldset>

      <fieldset className="brief-section">
        <legend>Ideal candidate profile</legend>
        <label className="field">
          Tone
          <textarea
            rows={2}
            value={ideal.tone}
            onChange={(e) =>
              onChange({
                ...value,
                ideal_candidate: { ...ideal, tone: e.target.value },
              })
            }
          />
        </label>
        <label className="field">
          Decision framework
          <textarea
            rows={3}
            value={ideal.decision_framework}
            onChange={(e) =>
              onChange({
                ...value,
                ideal_candidate: { ...ideal, decision_framework: e.target.value },
              })
            }
          />
        </label>
        <label className="field">
          Escalation rules
          <textarea
            rows={3}
            value={ideal.escalation_rules}
            onChange={(e) =>
              onChange({
                ...value,
                ideal_candidate: { ...ideal, escalation_rules: e.target.value },
              })
            }
          />
        </label>
      </fieldset>

      {showYourTake ? (
        <label className="field">
          Your take
          <textarea
            rows={4}
            value={value.your_take}
            onChange={(e) => onChange({ ...value, your_take: e.target.value })}
          />
        </label>
      ) : null}
    </div>
  );
}
