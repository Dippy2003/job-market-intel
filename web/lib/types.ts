/** JSON shapes from the read-only FastAPI. Decimals are normalized to numbers. */

export type HealthResponse = {
  status: string;
};

export type Job = {
  id: number;
  source: string;
  url: string;
  title: string;
  company: string | null;
  location: string | null;
  posted_date: string | null;
  duplicate_of: number | null;
  skills: string[];
};

export type JobListResponse = {
  items: Job[];
  total: number;
  limit: number;
  offset: number;
};

export type TrendPoint = {
  period_start: string;
  count: number;
  share: number;
};

export type SkillTrendSeries = {
  skill_id: number;
  skill: string;
  category: string | null;
  points: TrendPoint[];
};

export type SkillTrendsResponse = {
  items: SkillTrendSeries[];
};

export type ForecastPoint = {
  ds: string;
  yhat: number;
  yhat_lower: number;
  yhat_upper: number;
  model_version: string;
};

export type SkillForecast = {
  skill_id: number;
  skill: string;
  category: string | null;
  points: ForecastPoint[];
};

export type SkillForecastsResponse = {
  horizon_weeks: number;
  items: SkillForecast[];
};

export type Role = {
  id: number;
  label: string;
  top_skills: string[];
  job_count: number;
  run_at: string;
};

export type RoleListResponse = {
  items: Role[];
};

export type RoleJob = {
  id: number;
  source: string;
  url: string;
  title: string;
  company: string | null;
  location: string | null;
};

export type RoleDetail = Role & {
  jobs: RoleJob[];
};
