import type { ForecastPoint, SkillTrendSeries, TrendPoint } from "@/lib/types";

/** Same preference as the Streamlit dashboard when two models share a week. */
export const PREFERRED_MODEL = "prophet-weekly-1";

export const TOP_SKILL_LIMIT = 12;

export type RankedSkill = {
  skill: string;
  category: string | null;
  count: number;
  share: number;
  week: string;
};

export type ChartRow = {
  date: string;
  demand: number | null;
  forecast: number | null;
  lower: number | null;
  upper: number | null;
  model: string | null;
};

export function firstQuery(value: string | string[] | undefined): string | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  const text = raw?.trim();
  return text ? text : undefined;
}

export function parseRoleId(value: string | undefined): number | undefined {
  if (!value || !/^[1-9]\d*$/.test(value)) return undefined;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : undefined;
}

export function dashboardHref(skill?: string, role?: string): string {
  const params = new URLSearchParams();
  if (skill) params.set("skill", skill);
  if (role) params.set("role", role);
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

export function safeHttpUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol === "http:" || url.protocol === "https:") return url.toString();
  } catch {
    return null;
  }
  return null;
}

/** Latest stored week, highest job count first. That week is current demand. */
export function rankSkillsByDemand(
  items: SkillTrendSeries[],
  limit = TOP_SKILL_LIMIT,
): RankedSkill[] {
  const ranked: RankedSkill[] = [];
  for (const item of items) {
    const point = [...item.points].sort((a, b) => a.period_start.localeCompare(b.period_start)).at(-1);
    if (!point || !item.skill) continue;
    ranked.push({
      skill: item.skill,
      category: item.category,
      count: point.count,
      share: point.share,
      week: point.period_start,
    });
  }
  ranked.sort((a, b) => b.count - a.count || a.skill.localeCompare(b.skill));
  return ranked.slice(0, limit);
}

export function resolveSkill(
  requested: string | undefined,
  items: SkillTrendSeries[],
): string | undefined {
  const ranked = rankSkillsByDemand(items, Number.POSITIVE_INFINITY);
  if (ranked.length === 0) return requested;
  if (!requested) return ranked[0]?.skill;
  const needle = requested.toLowerCase();
  return ranked.find((item) => item.skill.toLowerCase() === needle)?.skill ?? requested;
}

export function seriesForSkill(
  items: SkillTrendSeries[],
  skill: string | undefined,
): SkillTrendSeries | undefined {
  if (!skill) return undefined;
  const needle = skill.toLowerCase();
  return items.find((item) => item.skill.toLowerCase() === needle);
}

/** One forecast row per week. Prophet wins when two models share a date. */
export function collapseForecast(points: ForecastPoint[]): ForecastPoint[] {
  const chosen = new Map<string, ForecastPoint>();
  for (const point of points) {
    if (!point.ds) continue;
    const current = chosen.get(point.ds);
    if (!current || (point.model_version === PREFERRED_MODEL && current.model_version !== PREFERRED_MODEL)) {
      chosen.set(point.ds, point);
    }
  }
  return [...chosen.values()].sort((a, b) => a.ds.localeCompare(b.ds));
}

export function buildChartRows(history: TrendPoint[], forecast: ForecastPoint[]): ChartRow[] {
  const byDate = new Map<string, ChartRow>();
  for (const point of history) {
    if (!point.period_start) continue;
    byDate.set(point.period_start, {
      date: point.period_start,
      demand: point.count,
      forecast: null,
      lower: null,
      upper: null,
      model: null,
    });
  }
  for (const point of collapseForecast(forecast)) {
    const row = byDate.get(point.ds) ?? {
      date: point.ds,
      demand: null,
      forecast: null,
      lower: null,
      upper: null,
      model: null,
    };
    row.forecast = point.yhat;
    row.lower = point.yhat_lower;
    row.upper = point.yhat_upper;
    row.model = point.model_version;
    byDate.set(point.ds, row);
  }
  return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
}

export function formatWeek(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
}

export function formatShare(share: number): string {
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(share * 100)}%`;
}

export function formatJobs(count: number): string {
  return `${formatNumber(count)} ${count === 1 ? "job" : "jobs"}`;
}
