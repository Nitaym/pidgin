import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type {
  Agent,
  TokenTotals,
  TokenUsageBucket,
  TokenUsageSummary,
} from "../api/client";
import { useApp } from "../context/AppContext";

const INPUT_COLOR = "var(--accent, #4f8cff)";
const OUTPUT_COLOR = "var(--accent-2, #8a5cf6)";

function formatCost(micros: number): string {
  return `$${(micros / 1_000_000).toFixed(micros >= 1_000_000 ? 2 : 4)}`;
}

function fmt(n: number): string {
  return n.toLocaleString();
}

/** Compact token count for axis ticks: 1500 → "1.5k", 2_000_000 → "2M". */
function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n % 1_000 === 0 ? 0 : 1)}k`;
  return String(Math.round(n));
}

/** "2026-07-11" → "Jul 11" (formatted in UTC so it matches the bucket). */
function dayLabel(day: string): string {
  const dt = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(dt.getTime())) return day;
  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}

const ZERO_BUCKET: Omit<TokenUsageBucket, "bucket"> = {
  input_tokens: 0,
  output_tokens: 0,
  total_tokens: 0,
  cost_usd_micros: 0,
  invocation_count: 0,
};

/** Expand an hourly series to all 24 hours of `day`, zero-filling empty hours
 * so a drilled-in day always shows the whole day rather than only active hours. */
function fillHours(day: string, buckets: TokenUsageBucket[]): TokenUsageBucket[] {
  const byHour = new Map(buckets.map((b) => [b.bucket, b]));
  return Array.from({ length: 24 }, (_, h) => {
    const key = `${day}T${String(h).padStart(2, "0")}`;
    return byHour.get(key) ?? { bucket: key, ...ZERO_BUCKET };
  });
}

/** Expand a daily series to every day from the first to the last bucket,
 * zero-filling days with no calls so the graph shows a continuous timeline
 * rather than skipping over idle days. Buckets arrive sorted ascending. */
function fillDays(buckets: TokenUsageBucket[]): TokenUsageBucket[] {
  if (buckets.length === 0) return buckets;
  const byDay = new Map(buckets.map((b) => [b.bucket, b]));
  const out: TokenUsageBucket[] = [];
  const cursor = new Date(`${buckets[0].bucket}T00:00:00Z`);
  const last = buckets[buckets.length - 1].bucket;
  // Guard against a pathological range blowing up the DOM.
  for (let i = 0; i < 3660; i++) {
    const key = cursor.toISOString().slice(0, 10);
    out.push(byDay.get(key) ?? { bucket: key, ...ZERO_BUCKET });
    if (key >= last) break;
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return out;
}

function sumTotals(buckets: TokenUsageBucket[]): TokenTotals {
  return buckets.reduce<TokenTotals>(
    (acc, b) => ({
      input_tokens: acc.input_tokens + b.input_tokens,
      output_tokens: acc.output_tokens + b.output_tokens,
      total_tokens: acc.total_tokens + b.total_tokens,
      cost_usd_micros: acc.cost_usd_micros + b.cost_usd_micros,
      invocation_count: acc.invocation_count + b.invocation_count,
    }),
    { input_tokens: 0, output_tokens: 0, total_tokens: 0, cost_usd_micros: 0, invocation_count: 0 },
  );
}

/** Start of `daysAgo` days ago, in UTC, as an ISO timestamp. */
function utcDaysAgo(daysAgo: number): string {
  const d = new Date();
  d.setUTCHours(0, 0, 0, 0);
  d.setUTCDate(d.getUTCDate() - daysAgo);
  return d.toISOString();
}

const TILE_LABEL: CSSProperties = {
  fontSize: "0.72rem",
  textTransform: "uppercase",
  letterSpacing: "0.05em",
};

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="panel stack" style={{ gap: "0.25rem", minWidth: "9rem", flex: "1 1 9rem" }}>
      <span className="muted" style={TILE_LABEL}>{label}</span>
      <span style={{ fontSize: "1.5rem", fontWeight: 600 }}>{value}</span>
      {sub ? <span className="muted" style={{ fontSize: "0.78rem" }}>{sub}</span> : null}
    </div>
  );
}

/** Two-up tile: the selected day on the left, all-time on the right. */
function SplitTile({
  label,
  dayValue,
  allValue,
  dayCaption,
  allCaption,
}: {
  label: string;
  dayValue: string;
  allValue: string;
  dayCaption: string;
  allCaption: string;
}) {
  return (
    <div className="panel stack" style={{ gap: "0.35rem", minWidth: "13rem", flex: "1 1 13rem" }}>
      <span className="muted" style={TILE_LABEL}>{label}</span>
      <div className="row" style={{ gap: "0.75rem", alignItems: "stretch" }}>
        <div className="stack" style={{ gap: "0.1rem", flex: 1 }}>
          <span style={{ fontSize: "1.5rem", fontWeight: 600 }}>{dayValue}</span>
          <span className="muted" style={{ fontSize: "0.72rem" }}>{dayCaption}</span>
        </div>
        <div
          className="stack"
          style={{ gap: "0.1rem", flex: 1, paddingLeft: "0.75rem", borderLeft: "1px solid var(--border, #2a2a2a)" }}
        >
          <span style={{ fontSize: "1.5rem", fontWeight: 600 }}>{allValue}</span>
          <span className="muted" style={{ fontSize: "0.72rem" }}>{allCaption}</span>
        </div>
      </div>
    </div>
  );
}

function UsageChart({
  buckets,
  granularity,
  onDrill,
}: {
  buckets: TokenUsageBucket[];
  granularity: "day" | "hour";
  onDrill: (bucket: string) => void;
}) {
  const max = useMemo(
    () => Math.max(1, ...buckets.map((b) => b.total_tokens)),
    [buckets],
  );
  if (buckets.length === 0) {
    return <p className="muted">No usage in this range.</p>;
  }
  const BAR_H = 160; // px the tallest bar fills
  const LABEL_H = 16; // px reserved under bars for the x-axis label
  // Four gridlines top→bottom: max, ¾, ½, ¼, 0.
  const ticks = [1, 0.75, 0.5, 0.25, 0].map((f) => Math.round(max * f));
  return (
    <div className="stack" style={{ gap: "0.5rem" }}>
      <div className="row" style={{ gap: "0.5rem", alignItems: "stretch" }}>
        {/* y-axis: token-count ticks aligned to the bar region */}
        <div
          className="muted"
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            alignItems: "flex-end",
            height: `${BAR_H}px`,
            paddingBottom: `${LABEL_H}px`,
            fontSize: "0.6rem",
            minWidth: "2.2rem",
          }}
        >
          {ticks.map((t, i) => (
            <span key={i}>{compact(t)}</span>
          ))}
        </div>
        <div
          className="row"
          style={{ gap: "0.35rem", alignItems: "flex-end", flex: 1, minWidth: 0 }}
        >
          {buckets.map((b) => {
            const inH = (b.input_tokens / max) * BAR_H;
            const outH = (b.output_tokens / max) * BAR_H;
            const label = granularity === "hour" ? `${b.bucket.slice(11)}:00` : b.bucket.slice(5);
            return (
              <button
                key={b.bucket}
                type="button"
                onClick={() => granularity === "day" && onDrill(b.bucket)}
                title={`${b.bucket}\n${fmt(b.input_tokens)} in / ${fmt(b.output_tokens)} out\n${fmt(b.total_tokens)} total · ${formatCost(b.cost_usd_micros)} · ${b.invocation_count} calls`}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "flex-end",
                  alignItems: "center",
                  flex: "1 1 0",
                  minWidth: 0,
                  height: `${BAR_H + LABEL_H}px`,
                  background: "none",
                  border: "none",
                  padding: 0,
                  cursor: granularity === "day" ? "pointer" : "default",
                }}
              >
                <div style={{ width: "80%", height: `${outH}px`, background: OUTPUT_COLOR, borderRadius: "2px 2px 0 0" }} />
                <div style={{ width: "80%", height: `${inH}px`, background: INPUT_COLOR, borderRadius: outH > 0 ? 0 : "2px 2px 0 0" }} />
                <span className="muted" style={{ height: `${LABEL_H}px`, fontSize: "0.6rem", marginTop: "0.2rem", whiteSpace: "nowrap", overflow: "hidden" }}>
                  {label}
                </span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="row muted" style={{ gap: "1rem", fontSize: "0.75rem" }}>
        <span><span style={{ display: "inline-block", width: "0.7rem", height: "0.7rem", background: INPUT_COLOR, borderRadius: "2px", marginRight: "0.3rem", verticalAlign: "middle" }} />input</span>
        <span><span style={{ display: "inline-block", width: "0.7rem", height: "0.7rem", background: OUTPUT_COLOR, borderRadius: "2px", marginRight: "0.3rem", verticalAlign: "middle" }} />output</span>
        {granularity === "day" ? <span>Click a day to drill into hours.</span> : null}
      </div>
    </div>
  );
}

function TotalsRow({ t }: { t: TokenTotals }) {
  return (
    <>
      <td style={{ textAlign: "right" }}>{fmt(t.input_tokens)}</td>
      <td style={{ textAlign: "right" }}>{fmt(t.output_tokens)}</td>
      <td style={{ textAlign: "right" }}>{fmt(t.total_tokens)}</td>
      <td style={{ textAlign: "right" }}>{formatCost(t.cost_usd_micros)}</td>
      <td style={{ textAlign: "right" }}>{fmt(t.invocation_count)}</td>
    </>
  );
}

const TH_NUM: CSSProperties = { textAlign: "right", padding: "0.3rem 0.5rem" };
const TH_LEFT: CSSProperties = { textAlign: "left", padding: "0.3rem 0.5rem" };

export function UsagePage() {
  const { workspace } = useApp();
  const slug = workspace?.slug ?? "";

  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [summary, setSummary] = useState<TokenUsageSummary | null>(null);
  // The series is stored together with the drilldown it was fetched for, and
  // only ever replaced as one atomic snapshot when a fetch resolves. Deriving
  // the chart from this (not from the URL `drillDay`, which changes the instant
  // you click) means the graph transitions exactly once, with no flash of a
  // mismatched new-filter / old-data frame in between.
  const [series, setSeries] = useState<{
    drillDay: string | null;
    granularity: "day" | "hour";
    buckets: TokenUsageBucket[];
  }>({ drillDay: null, granularity: "day", buckets: [] });
  const [error, setError] = useState<string | null>(null);

  // Filters live in the URL (?agent=…&day=…) so each change is a real browser
  // history entry — the Back button then undoes the last filter natively.
  const agentId = searchParams.get("agent") ?? "";
  const drillDay = searchParams.get("day");
  const hasFilter = Boolean(agentId || drillDay);

  const setFilters = (next: { agentId?: string; drillDay?: string | null }) => {
    const params = new URLSearchParams(searchParams);
    if (next.agentId !== undefined) {
      if (next.agentId) params.set("agent", next.agentId);
      else params.delete("agent");
    }
    if (next.drillDay !== undefined) {
      if (next.drillDay) params.set("day", next.drillDay);
      else params.delete("day");
    }
    setSearchParams(params); // pushes a history entry (no replace)
  };

  useEffect(() => {
    if (!slug) return;
    api.listAgents(slug).then(setAgents).catch(() => setAgents([]));
  }, [slug]);

  const load = useCallback(async () => {
    if (!slug) return;
    try {
      const agentOpt = agentId ? { agentId } : {};
      const [sum, ser] = await Promise.all([
        api.tokenUsageSummary(slug, agentOpt),
        drillDay
          ? api.tokenUsageSeries(slug, {
              granularity: "hour",
              start: `${drillDay}T00:00:00.000Z`,
              end: `${drillDay}T23:59:59.999Z`,
              ...agentOpt,
            })
          : api.tokenUsageSeries(slug, { granularity: "day", ...agentOpt }),
      ]);
      setSummary(sum);
      setSeries({ drillDay, granularity: ser.granularity, buckets: ser.buckets });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load usage");
    }
  }, [slug, agentId, drillDay]);

  useEffect(() => {
    void load();
  }, [load]);

  // Everything below reflects the resolved snapshot (`series`), not the URL, so
  // the chart, tiles and header all flip together on the one fetch that lands.
  const activeDrill = series.drillDay;

  // "Last 30 days" tile: derived from the daily series (already all-time) so we
  // don't fire an extra windowed request. Only meaningful in the daily view.
  const last30 = useMemo(() => {
    if (series.drillDay) return null;
    const cutoff = utcDaysAgo(30).slice(0, 10);
    const today = new Date().toISOString().slice(0, 10);
    let inTok = 0;
    let outTok = 0;
    let todayTok = 0;
    for (const b of series.buckets) {
      if (b.bucket >= cutoff) {
        inTok += b.input_tokens;
        outTok += b.output_tokens;
      }
      if (b.bucket === today) todayTok = b.total_tokens;
    }
    return { total30: inTok + outTok, today: todayTok };
  }, [series]);

  // When drilled into a day, the hourly buckets ARE that day's usage — sum them
  // for the day-scoped stat tiles (no extra request needed).
  const dayTotals = useMemo(
    () => (series.drillDay ? sumTotals(series.buckets) : null),
    [series],
  );

  // Zero-fill gaps so the graph is a continuous timeline: the whole day (all 24
  // hours) when drilled in, and every calendar day in range in the daily view.
  const displayBuckets = useMemo(() => {
    if (series.drillDay && series.granularity === "hour") return fillHours(series.drillDay, series.buckets);
    if (!series.drillDay && series.granularity === "day") return fillDays(series.buckets);
    return series.buckets;
  }, [series]);

  const totals = summary?.totals;
  const dayCaption = activeDrill ? dayLabel(activeDrill) : "";

  return (
    <div className="stack">
      <div className="page-header">
        <h2>Usage</h2>
        <div className="page-header-actions">
          {hasFilter ? (
            <button type="button" className="secondary" onClick={() => navigate(-1)}>
              ← Back
            </button>
          ) : null}
          <select
            value={agentId}
            onChange={(e) => setFilters({ agentId: e.target.value, drillDay: null })}
          >
            <option value="">All agents</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.display_name} @{a.handle}
              </option>
            ))}
          </select>
        </div>
      </div>
      <p className="muted">
        Tokens and estimated cost across every LLM call, summed from the permanent
        per-call record. Buckets are UTC.
      </p>

      {error ? <div className="error">{error}</div> : null}

      {totals && dayTotals && activeDrill ? (
        <div className="row" style={{ gap: "0.75rem", flexWrap: "wrap" }}>
          <SplitTile
            label="Total tokens"
            dayValue={fmt(dayTotals.total_tokens)}
            allValue={fmt(totals.total_tokens)}
            dayCaption={dayCaption}
            allCaption="all time"
          />
          <SplitTile
            label="Est. cost"
            dayValue={formatCost(dayTotals.cost_usd_micros)}
            allValue={formatCost(totals.cost_usd_micros)}
            dayCaption={dayCaption}
            allCaption="all time"
          />
          <SplitTile
            label="LLM calls"
            dayValue={fmt(dayTotals.invocation_count)}
            allValue={fmt(totals.invocation_count)}
            dayCaption={dayCaption}
            allCaption="all time"
          />
        </div>
      ) : totals ? (
        <div className="row" style={{ gap: "0.75rem", flexWrap: "wrap" }}>
          <Tile label="Total tokens" value={fmt(totals.total_tokens)} sub={`${fmt(totals.input_tokens)} in · ${fmt(totals.output_tokens)} out`} />
          <Tile label="Est. cost" value={formatCost(totals.cost_usd_micros)} sub="all time" />
          <Tile label="LLM calls" value={fmt(totals.invocation_count)} sub="all time" />
          {last30 ? <Tile label="Last 30 days" value={fmt(last30.total30)} sub={`today: ${fmt(last30.today)}`} /> : null}
        </div>
      ) : null}

      <div className="panel stack" style={{ gap: "0.75rem" }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
          <h3 style={{ margin: 0 }}>
            {activeDrill ? `Hourly — ${dayLabel(activeDrill)}` : "Daily usage"}
          </h3>
          {activeDrill ? <span className="muted" style={{ fontSize: "0.8rem" }}>Click ← Back to return to the daily view.</span> : null}
        </div>
        <UsageChart
          buckets={displayBuckets}
          granularity={series.granularity}
          onDrill={(b) => setFilters({ drillDay: b })}
        />
      </div>

      {summary && !agentId && summary.by_agent.length > 0 ? (
        <div className="panel stack" style={{ gap: "0.5rem" }}>
          <h3 style={{ margin: 0 }}>By agent</h3>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr className="muted">
                <th style={TH_LEFT}>Agent</th>
                <th style={TH_NUM}>Input</th>
                <th style={TH_NUM}>Output</th>
                <th style={TH_NUM}>Total</th>
                <th style={TH_NUM}>Cost</th>
                <th style={TH_NUM}>Calls</th>
              </tr>
            </thead>
            <tbody>
              {summary.by_agent.map((a) => (
                <tr key={a.ai_employee_id} style={{ borderTop: "1px solid var(--border, #2a2a2a)" }}>
                  <td style={{ padding: "0.3rem 0.5rem" }}>
                    {a.agent_display_name ?? a.ai_employee_id}
                    {a.agent_handle ? <span className="muted"> @{a.agent_handle}</span> : null}
                  </td>
                  <TotalsRow t={a} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {summary && summary.by_model.length > 0 ? (
        <div className="panel stack" style={{ gap: "0.5rem" }}>
          <h3 style={{ margin: 0 }}>By model</h3>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr className="muted">
                <th style={TH_LEFT}>Model</th>
                <th style={TH_NUM}>Input</th>
                <th style={TH_NUM}>Output</th>
                <th style={TH_NUM}>Total</th>
                <th style={TH_NUM}>Cost</th>
                <th style={TH_NUM}>Calls</th>
              </tr>
            </thead>
            <tbody>
              {summary.by_model.map((m) => (
                <tr key={`${m.provider}:${m.model_id}`} style={{ borderTop: "1px solid var(--border, #2a2a2a)" }}>
                  <td style={{ padding: "0.3rem 0.5rem" }}>
                    {m.model_id}
                    <span className="muted"> · {m.provider}</span>
                  </td>
                  <TotalsRow t={m} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
