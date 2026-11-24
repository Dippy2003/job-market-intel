import Link from "next/link";
import { connection } from "next/server";

import { SkillChart } from "@/components/skill-chart";
import { ApiError, apiBaseUrl, loadDashboard, type DashboardData } from "@/lib/api";
import {
  TOP_SKILL_LIMIT,
  dashboardHref,
  firstQuery,
  formatJobs,
  formatNumber,
  formatShare,
  formatWeek,
  parseRoleId,
  rankSkillsByDemand,
  safeHttpUrl,
  seriesForSkill,
} from "@/lib/series";

export const dynamic = "force-dynamic";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  await connection();
  const query = await searchParams;
  const requestedSkill = firstQuery(query.skill);
  const roleQuery = firstQuery(query.role);
  const roleId = parseRoleId(roleQuery);

  let data: DashboardData | undefined;
  let failure: string | undefined;
  try {
    data = await loadDashboard({ skill: requestedSkill, roleId });
  } catch (error) {
    failure = error instanceof ApiError ? error.message : "API not reachable";
  }

  if (!data) {
    return <Unreachable message={failure ?? "API not reachable"} />;
  }

  return (
    <Dashboard
      data={data}
      roleQuery={roleQuery}
      roleInvalid={roleQuery !== undefined && roleId === undefined}
    />
  );
}

function Unreachable({ message }: { message: string }) {
  return (
    <main className="page">
      <Header status="down" showNav={false} />
      <section className="panel banner" role="alert">
        <h2>API not reachable</h2>
        <p>
          Start it from the repository root with <code>uvicorn api.main:app</code>, then refresh
          this page.
        </p>
        {message === "API not reachable" ? null : <p>{message}</p>}
        <p>
          Configured base URL: <code>{apiBaseUrl()}</code>
        </p>
      </section>
    </main>
  );
}

function Header({ status, showNav = true }: { status: string; showNav?: boolean }) {
  return (
    <header className="masthead">
      <div>
        <p className="eyebrow">Sri Lanka tech hiring</p>
        <h1>Job Market Intelligence</h1>
        <p className="lede">
          Top skills by weekly demand, a trend and forecast for the skill you pick, and the role
          clusters those postings fall into.
        </p>
        <p className="status">
          API {status} at <code>{apiBaseUrl()}</code>
        </p>
      </div>
      {showNav ? (
        <nav className="section-nav" aria-label="Sections">
          <a href="#demand">Demand</a>
          <a href="#forecast">Forecast</a>
          <a href="#roles">Roles</a>
          <a href="#jobs">Jobs</a>
        </nav>
      ) : null}
    </header>
  );
}

function Dashboard({
  data,
  roleQuery,
  roleInvalid,
}: {
  data: DashboardData;
  roleQuery: string | undefined;
  roleInvalid: boolean;
}) {
  const ranked = rankSkillsByDemand(data.trends.items, Number.POSITIVE_INFINITY);
  const top = ranked.slice(0, TOP_SKILL_LIMIT);
  const selected = data.selectedSkill;
  const history = seriesForSkill(data.trends.items, selected);
  const forecast = data.forecasts.items.find(
    (item) => item.skill.toLowerCase() === selected?.toLowerCase(),
  );
  const category = history?.category ?? forecast?.category ?? null;
  const roleKey = roleInvalid ? undefined : roleQuery;
  const maxDemand = top[0]?.count || 1;
  const maxJobs = data.roles.items.reduce((max, role) => Math.max(max, role.job_count), 1);
  const skillOptions =
    selected && !ranked.some((item) => item.skill === selected)
      ? [{ skill: selected }, ...ranked]
      : ranked;

  return (
    <main className="page">
      <a className="skip" href="#demand">
        Skip to demand
      </a>
      <Header status={data.health.status || "ok"} />
      <div className="split">
        <section className="panel" id="demand" aria-labelledby="demand-heading">
          <h2 id="demand-heading">Top skills by demand</h2>
          <p className="section-note">Ranked by jobs in each skill&apos;s latest stored week.</p>
          {top.length === 0 ? (
            <p className="empty">No skill trends yet. Run python -m pipeline.compute_trends.</p>
          ) : (
            <ol className="skill-list">
              {top.map((skill) => (
                <li key={skill.skill}>
                  <Link
                    href={dashboardHref(skill.skill, roleKey)}
                    className={skill.skill === selected ? "skill is-selected" : "skill"}
                    aria-current={skill.skill === selected ? "true" : undefined}
                  >
                    <span className="skill-name">
                      {skill.skill}
                      <span className="meta">{formatNumber(skill.count)}</span>
                    </span>
                    <span className="bar" aria-hidden="true">
                      <span style={{ width: `${Math.max(6, (skill.count / maxDemand) * 100)}%` }} />
                    </span>
                    <span className="meta">
                      {formatShare(skill.share)} of postings in the week of {formatWeek(skill.week)}
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          )}
        </section>

        <section className="panel" id="forecast" aria-labelledby="forecast-heading">
          <h2 id="forecast-heading">
            {selected ? selected : "Trend and forecast"}
            {category ? <span className="meta"> {category}</span> : null}
          </h2>
          <p className="section-note">
            Solid line: jobs that mention the skill each week. Dashed line: the stored{" "}
            {data.forecasts.horizon_weeks}-week forecast. Prophet is used when two models share a
            week.
          </p>
          {ranked.length === 0 ? (
            <p className="empty">No skill trends yet. Run python -m pipeline.compute_trends.</p>
          ) : (
            <form className="picker" action="/" method="get">
              {roleKey ? <input type="hidden" name="role" value={roleKey} /> : null}
              <label>
                Skill
                <select name="skill" defaultValue={selected}>
                  {skillOptions.map((item) => (
                    <option key={item.skill} value={item.skill}>
                      {item.skill}
                    </option>
                  ))}
                </select>
              </label>
              <button type="submit">Show</button>
            </form>
          )}
          {selected ? (
            <SkillChart
              skill={selected}
              history={history?.points ?? []}
              forecast={forecast?.points ?? []}
            />
          ) : null}
        </section>
      </div>

      <section className="panel stack" id="roles" aria-labelledby="roles-heading">
        <div>
          <h2 id="roles-heading">Roles</h2>
          <p className="section-note">
            Clusters from the latest run. Open one to see the jobs assigned to it.
          </p>
          {roleInvalid ? <p className="empty">Role ids are whole numbers.</p> : null}
          {data.role.missing ? <p className="empty">That role was not found.</p> : null}
          {data.roles.items.length === 0 ? (
            <p className="empty">No role clusters yet. Run python -m pipeline.cluster_roles.</p>
          ) : (
            <ol className="role-list">
              {data.roles.items.map((role) => {
                const open = data.role.detail?.id === role.id;
                return (
                  <li className="role" key={role.id}>
                    <div className="role-head">
                      <h3 className="role-name">
                        {role.label}
                        <span className="meta">{formatJobs(role.job_count)}</span>
                      </h3>
                      <Link
                        className="action"
                        href={
                          open
                            ? dashboardHref(selected)
                            : dashboardHref(selected, String(role.id))
                        }
                      >
                        {open ? "Hide jobs" : "View jobs"}
                      </Link>
                    </div>
                    <span className="bar" aria-hidden="true">
                      <span style={{ width: `${Math.max(6, (role.job_count / maxJobs) * 100)}%` }} />
                    </span>
                    {role.top_skills.length > 0 ? (
                      <ul className="chips">
                        {role.top_skills.map((skill) => (
                          <li key={skill}>{skill}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="meta">No top skills stored.</p>
                    )}
                    {open && data.role.detail ? (
                      data.role.detail.jobs.length === 0 ? (
                        <p className="empty">No jobs are assigned to this role.</p>
                      ) : (
                        <ul className="jobs">
                          {data.role.detail.jobs.map((job) => {
                            const href = safeHttpUrl(job.url);
                            const place = [job.company, job.location, job.source]
                              .filter(Boolean)
                              .join(" · ");
                            return (
                              <li key={job.id}>
                                {href ? (
                                  <a href={href} rel="noreferrer">
                                    {job.title}
                                  </a>
                                ) : (
                                  job.title
                                )}
                                {place ? <span className="meta"> {place}</span> : null}
                              </li>
                            );
                          })}
                        </ul>
                      )
                    ) : null}
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </section>

      <section className="panel" id="jobs" aria-labelledby="jobs-heading">
        <h2 id="jobs-heading">
          {selected ? `Recent postings that ask for ${selected}` : "Recent postings"}
        </h2>
        {data.jobs.total > 0 ? (
          <p className="section-note">
            Showing {data.jobs.items.length} of {formatNumber(data.jobs.total)}.
          </p>
        ) : null}
        {data.jobs.items.length === 0 ? (
          <p className="empty">No jobs match.</p>
        ) : (
          <div className="table-scroll">
          <table>
            <caption>Jobs from the read-only API</caption>
            <thead>
              <tr>
                <th scope="col">Title</th>
                <th scope="col">Company</th>
                <th scope="col">Location</th>
                <th scope="col">Source</th>
                <th scope="col">Posted</th>
                <th scope="col">Skills</th>
              </tr>
            </thead>
            <tbody>
              {data.jobs.items.map((job) => {
                const href = safeHttpUrl(job.url);
                return (
                  <tr key={job.id}>
                    <td>
                      {href ? (
                        <a className="job-title" href={href} rel="noreferrer">
                          {job.title}
                        </a>
                      ) : (
                        <span className="job-title">{job.title}</span>
                      )}
                      {job.duplicate_of !== null ? <span className="tag">Duplicate</span> : null}
                    </td>
                    <td>{job.company ?? "—"}</td>
                    <td>{job.location ?? "—"}</td>
                    <td>{job.source || "—"}</td>
                    <td>{job.posted_date ? formatWeek(job.posted_date) : "—"}</td>
                    <td>{job.skills.length > 0 ? job.skills.join(", ") : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        )}
      </section>
    </main>
  );
}
