import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildChartRows,
  collapseForecast,
  formatJobs,
  parseRoleId,
  rankSkillsByDemand,
  resolveSkill,
  safeHttpUrl,
} from "./series.ts";
import type { SkillTrendSeries } from "./types.ts";

const trends: SkillTrendSeries[] = [
  {
    skill_id: 1,
    skill: "Python",
    category: "language",
    points: [
      { period_start: "2026-11-16", count: 4, share: 0.8 },
      { period_start: "2026-11-02", count: 9, share: 0.5 },
    ],
  },
  {
    skill_id: 2,
    skill: "SQL",
    category: "database",
    points: [{ period_start: "2026-11-16", count: 5, share: 1 }],
  },
];

describe("rankSkillsByDemand", () => {
  it("uses the latest week, not an earlier higher count", () => {
    const ranked = rankSkillsByDemand(trends, 10);
    assert.deepEqual(
      ranked.map((item) => [item.skill, item.count, item.week]),
      [
        ["SQL", 5, "2026-11-16"],
        ["Python", 4, "2026-11-16"],
      ],
    );
  });
});

describe("resolveSkill", () => {
  it("defaults to the highest latest demand and matches case-insensitively", () => {
    assert.equal(resolveSkill(undefined, trends), "SQL");
    assert.equal(resolveSkill("python", trends), "Python");
    assert.equal(resolveSkill("Rust", trends), "Rust");
  });
});

describe("collapseForecast", () => {
  it("keeps prophet when two models share a week", () => {
    const rows = collapseForecast([
      {
        ds: "2026-11-23",
        yhat: 1,
        yhat_lower: 0,
        yhat_upper: 2,
        model_version: "linear-fallback-1",
      },
      {
        ds: "2026-11-23",
        yhat: 3,
        yhat_lower: 2,
        yhat_upper: 4,
        model_version: "prophet-weekly-1",
      },
      {
        ds: "2026-11-30",
        yhat: 6,
        yhat_lower: 5,
        yhat_upper: 7,
        model_version: "linear-fallback-1",
      },
    ]);
    assert.deepEqual(
      rows.map((row) => [row.ds, row.yhat, row.model_version]),
      [
        ["2026-11-23", 3, "prophet-weekly-1"],
        ["2026-11-30", 6, "linear-fallback-1"],
      ],
    );
  });
});

describe("buildChartRows", () => {
  it("lines history and forecast up on the same dates", () => {
    const rows = buildChartRows(
      [{ period_start: "2026-11-16", count: 4, share: 0.8 }],
      [
        {
          ds: "2026-11-23",
          yhat: 3,
          yhat_lower: 2,
          yhat_upper: 4,
          model_version: "prophet-weekly-1",
        },
      ],
    );
    assert.equal(rows[0]?.demand, 4);
    assert.equal(rows[0]?.forecast, null);
    assert.equal(rows[1]?.date, "2026-11-23");
    assert.equal(rows[1]?.forecast, 3);
  });
});

describe("formatJobs", () => {
  it("uses the singular only for one job", () => {
    assert.equal(formatJobs(1), "1 job");
    assert.equal(formatJobs(2), "2 jobs");
  });
});

describe("guards", () => {
  it("rejects role ids and urls that are not safe to request or link", () => {
    assert.equal(parseRoleId("2"), 2);
    assert.equal(parseRoleId("0"), undefined);
    assert.equal(parseRoleId("abc"), undefined);
    assert.equal(safeHttpUrl("https://itpro.lk/jobs/1"), "https://itpro.lk/jobs/1");
    assert.equal(safeHttpUrl("javascript:alert(1)"), null);
  });
});
