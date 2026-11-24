import { connection } from "next/server";

import { resolveSkill } from "@/lib/series";
import type {
  ForecastPoint,
  HealthResponse,
  Job,
  JobListResponse,
  Role,
  RoleDetail,
  RoleJob,
  RoleListResponse,
  SkillForecast,
  SkillForecastsResponse,
  SkillTrendSeries,
  SkillTrendsResponse,
  TrendPoint,
} from "@/lib/types";

const DEFAULT_BASE_URL = "http://127.0.0.1:8000";
const TIMEOUT_MS = 8000;

type Query = Record<string, string | number | undefined>;

export class ApiError extends Error {
  status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export type RoleLoad = {
  detail: RoleDetail | null;
  missing: boolean;
};

export type DashboardData = {
  baseUrl: string;
  health: HealthResponse;
  trends: SkillTrendsResponse;
  forecasts: SkillForecastsResponse;
  roles: RoleListResponse;
  jobs: JobListResponse;
  role: RoleLoad;
  selectedSkill: string | undefined;
};

export function apiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  return (configured || DEFAULT_BASE_URL).replace(/\/+$/, "");
}

function asNumber(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
}

function asString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text || null;
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim() !== "");
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

export async function apiGet<T>(path: string, query?: Query): Promise<T> {
  const url = new URL(path, `${apiBaseUrl()}/`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === "") continue;
      url.searchParams.set(key, String(value));
    }
  }
  let response: Response;
  try {
    response = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    throw new ApiError("API not reachable");
  }
  const text = await response.text();
  if (!response.ok) {
    throw new ApiError(`API ${response.status} for ${path}`, response.status);
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(`API returned a non-JSON response for ${path}`, response.status);
  }
}

function normalizeHealth(body: unknown): HealthResponse {
  const record = asRecord(body);
  const status = asString(record?.status);
  return { status: status ?? "ok" };
}

function normalizePoint(value: unknown): TrendPoint | null {
  const record = asRecord(value);
  const period = asString(record?.period_start);
  if (!record || !period) return null;
  return {
    period_start: period,
    count: asNumber(record.count),
    share: asNumber(record.share),
  };
}

function normalizeTrends(body: unknown): SkillTrendsResponse {
  const items = Array.isArray(asRecord(body)?.items) ? (asRecord(body)?.items as unknown[]) : [];
  const series: SkillTrendSeries[] = [];
  for (const item of items) {
    const record = asRecord(item);
    const skill = asString(record?.skill);
    if (!record || !skill) continue;
    const points = Array.isArray(record.points)
      ? record.points.map(normalizePoint).filter((point): point is TrendPoint => point !== null)
      : [];
    series.push({
      skill_id: asNumber(record.skill_id),
      skill,
      category: asString(record.category),
      points,
    });
  }
  return { items: series };
}

function normalizeForecastPoint(value: unknown): ForecastPoint | null {
  const record = asRecord(value);
  const ds = asString(record?.ds);
  if (!record || !ds) return null;
  return {
    ds,
    yhat: asNumber(record.yhat),
    yhat_lower: asNumber(record.yhat_lower),
    yhat_upper: asNumber(record.yhat_upper),
    model_version: asString(record.model_version) ?? "",
  };
}

function normalizeForecasts(body: unknown): SkillForecastsResponse {
  const record = asRecord(body);
  const items = Array.isArray(record?.items) ? record.items : [];
  const forecasts: SkillForecast[] = [];
  for (const item of items) {
    const row = asRecord(item);
    const skill = asString(row?.skill);
    if (!row || !skill) continue;
    const points = Array.isArray(row.points)
      ? row.points.map(normalizeForecastPoint).filter((point): point is ForecastPoint => point !== null)
      : [];
    forecasts.push({
      skill_id: asNumber(row.skill_id),
      skill,
      category: asString(row.category),
      points,
    });
  }
  const horizon = asNumber(record?.horizon_weeks);
  return { horizon_weeks: horizon || 8, items: forecasts };
}

function normalizeRole(value: unknown): Role | null {
  const record = asRecord(value);
  const label = asString(record?.label);
  if (!record || !label) return null;
  return {
    id: asNumber(record.id),
    label,
    top_skills: asStringList(record.top_skills),
    job_count: asNumber(record.job_count),
    run_at: asString(record.run_at) ?? "",
  };
}

function normalizeRoles(body: unknown): RoleListResponse {
  const items = Array.isArray(asRecord(body)?.items) ? (asRecord(body)?.items as unknown[]) : [];
  return {
    items: items.map(normalizeRole).filter((role): role is Role => role !== null),
  };
}

function normalizeJob(value: unknown): Job | null {
  const record = asRecord(value);
  const title = asString(record?.title);
  if (!record || !title) return null;
  const duplicate = record.duplicate_of;
  return {
    id: asNumber(record.id),
    source: asString(record.source) ?? "",
    url: asString(record.url) ?? "",
    title,
    company: asString(record.company),
    location: asString(record.location),
    posted_date: asString(record.posted_date),
    duplicate_of: duplicate === null || duplicate === undefined ? null : asNumber(duplicate),
    skills: asStringList(record.skills),
  };
}

function normalizeJobs(body: unknown): JobListResponse {
  const record = asRecord(body);
  const items = Array.isArray(record?.items) ? record.items : [];
  return {
    items: items.map(normalizeJob).filter((job): job is Job => job !== null),
    total: asNumber(record?.total),
    limit: asNumber(record?.limit),
    offset: asNumber(record?.offset),
  };
}

function normalizeRoleJob(value: unknown): RoleJob | null {
  const record = asRecord(value);
  const title = asString(record?.title);
  if (!record || !title) return null;
  return {
    id: asNumber(record.id),
    source: asString(record.source) ?? "",
    url: asString(record.url) ?? "",
    title,
    company: asString(record.company),
    location: asString(record.location),
  };
}

function normalizeRoleDetail(body: unknown): RoleDetail | null {
  const role = normalizeRole(body);
  if (!role) return null;
  const jobs = Array.isArray(asRecord(body)?.jobs) ? (asRecord(body)?.jobs as unknown[]) : [];
  return {
    ...role,
    jobs: jobs.map(normalizeRoleJob).filter((job): job is RoleJob => job !== null),
  };
}

async function loadRole(roleId: number | undefined): Promise<RoleLoad> {
  if (roleId === undefined) return { detail: null, missing: false };
  try {
    const body = await apiGet<unknown>(`/roles/${roleId}`);
    const detail = normalizeRoleDetail(body);
    if (!detail) throw new ApiError(`API returned an unexpected response for /roles/${roleId}`);
    return { detail, missing: false };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return { detail: null, missing: true };
    throw error;
  }
}

export async function loadDashboard(input: {
  skill?: string;
  roleId?: number;
}): Promise<DashboardData> {
  await connection();
  // A skill in the query can be sent with the other reads. The default skill is
  // only known after trends come back, so that jobs request waits.
  const [healthBody, trendsBody, forecastsBody, rolesBody, role, jobsForQuery] = await Promise.all([
    apiGet<unknown>("/health"),
    apiGet<unknown>("/skills/trends"),
    apiGet<unknown>("/skills/forecasts"),
    apiGet<unknown>("/roles"),
    loadRole(input.roleId),
    input.skill === undefined
      ? Promise.resolve(null)
      : apiGet<unknown>("/jobs", { skill: input.skill, limit: 8 }),
  ]);
  const trends = normalizeTrends(trendsBody);
  const selectedSkill = resolveSkill(input.skill, trends.items);
  const jobsBody =
    jobsForQuery ??
    (await apiGet<unknown>("/jobs", {
      skill: selectedSkill,
      limit: 8,
    }));
  return {
    baseUrl: apiBaseUrl(),
    health: normalizeHealth(healthBody),
    trends,
    forecasts: normalizeForecasts(forecastsBody),
    roles: normalizeRoles(rolesBody),
    jobs: normalizeJobs(jobsBody),
    role,
    selectedSkill,
  };
}
