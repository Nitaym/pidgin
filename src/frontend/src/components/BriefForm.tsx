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
    <div className="brief-form stack">
      <section className="brief-section">
        <h3 className="brief-section-title">Job requirements</h3>
        <div className="field">
          <label htmlFor="brief-mission">Mission</label>
          <textarea
            id="brief-mission"
            rows={5}
            value={job.mission}
            onChange={(e) =>
              onChange({
                ...value,
                job_requirements: { ...job, mission: e.target.value },
              })
            }
          />
        </div>
        <div className="field">
          <label htmlFor="brief-responsibilities">Responsibilities (one per line)</label>
          <textarea
            id="brief-responsibilities"
            rows={6}
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
        </div>
        <div className="field">
          <label htmlFor="brief-out-of-scope">Out of scope (one per line)</label>
          <textarea
            id="brief-out-of-scope"
            rows={5}
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
        </div>
      </section>

      <section className="brief-section">
        <h3 className="brief-section-title">Ideal candidate profile</h3>
        <div className="field">
          <label htmlFor="brief-tone">Tone</label>
          <textarea
            id="brief-tone"
            rows={4}
            value={ideal.tone}
            onChange={(e) =>
              onChange({
                ...value,
                ideal_candidate: { ...ideal, tone: e.target.value },
              })
            }
          />
        </div>
        <div className="field">
          <label htmlFor="brief-decision-framework">Decision framework</label>
          <textarea
            id="brief-decision-framework"
            rows={5}
            value={ideal.decision_framework}
            onChange={(e) =>
              onChange({
                ...value,
                ideal_candidate: { ...ideal, decision_framework: e.target.value },
              })
            }
          />
        </div>
        <div className="field">
          <label htmlFor="brief-escalation-rules">Escalation rules</label>
          <textarea
            id="brief-escalation-rules"
            rows={5}
            value={ideal.escalation_rules}
            onChange={(e) =>
              onChange({
                ...value,
                ideal_candidate: { ...ideal, escalation_rules: e.target.value },
              })
            }
          />
        </div>
      </section>

      {showYourTake ? (
        <section className="brief-section">
          <h3 className="brief-section-title">Your take</h3>
          <div className="field">
            <label htmlFor="brief-your-take">Notes for this hire</label>
            <textarea
              id="brief-your-take"
              rows={6}
              placeholder="Anything specific to this role or candidate…"
              value={value.your_take}
              onChange={(e) => onChange({ ...value, your_take: e.target.value })}
            />
          </div>
        </section>
      ) : null}
    </div>
  );
}
