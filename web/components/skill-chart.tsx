import { buildChartRows, formatNumber, formatWeek } from "@/lib/series";
import type { ForecastPoint, TrendPoint } from "@/lib/types";

const WIDTH = 720;
const HEIGHT = 300;
const PAD = { top: 18, right: 18, bottom: 36, left: 44 };

function xAt(index: number, count: number): number {
  const inner = WIDTH - PAD.left - PAD.right;
  if (count <= 1) return PAD.left + inner / 2;
  return PAD.left + (index / (count - 1)) * inner;
}

function yAt(value: number, yMax: number): number {
  const inner = HEIGHT - PAD.top - PAD.bottom;
  return PAD.top + inner - (Math.max(0, value) / yMax) * inner;
}

function tickIndexes(count: number): number[] {
  if (count <= 1) return [0];
  const slots = Math.min(4, count);
  const indexes = new Set<number>();
  for (let slot = 0; slot < slots; slot += 1) {
    indexes.add(Math.round((slot * (count - 1)) / (slots - 1)));
  }
  return [...indexes].sort((left, right) => left - right);
}

function shortWeek(iso: string): string {
  return formatWeek(iso).replace(/ \d{4}$/, "");
}

export function SkillChart({
  skill,
  history,
  forecast,
}: {
  skill: string;
  history: TrendPoint[];
  forecast: ForecastPoint[];
}) {
  const rows = buildChartRows(history, forecast);
  if (rows.length === 0) {
    return <p className="empty">No trend or forecast is stored for {skill}.</p>;
  }

  const magnitudes = rows.flatMap((row) =>
    [row.demand, row.forecast, row.lower, row.upper].filter((value): value is number => value !== null),
  );
  const peak = Math.max(1, ...magnitudes);
  const yMax = peak * 1.08;
  const count = rows.length;
  const showDots = count <= 40;
  const dotRadius = 4;
  const forecastIndexes = rows.flatMap((row, index) => (row.forecast === null ? [] : [index]));
  const demandPoints = rows.flatMap((row, index) =>
    row.demand === null ? [] : [`${xAt(index, count)},${yAt(row.demand, yMax)}`],
  );
  const forecastPoints = forecastIndexes.map((index) => {
    const value = rows[index]?.forecast ?? 0;
    return `${xAt(index, count)},${yAt(value, yMax)}`;
  });
  const band =
    forecastIndexes.length > 1
      ? [
          ...forecastIndexes.map((index) => {
            const upper = rows[index]?.upper ?? rows[index]?.forecast ?? 0;
            return `${xAt(index, count)},${yAt(upper, yMax)}`;
          }),
          ...[...forecastIndexes].reverse().map((index) => {
            const lower = rows[index]?.lower ?? rows[index]?.forecast ?? 0;
            return `${xAt(index, count)},${yAt(lower, yMax)}`;
          }),
        ].join(" ")
      : null;
  const yTicks = [0, peak / 2, peak];
  const models = [...new Set(rows.flatMap((row) => (row.model ? [row.model] : [])))];

  return (
    <figure className="chart-block">
      <figcaption className="legend">
        <span>
          <i className="swatch swatch-demand" aria-hidden="true" />
          Demand
        </span>
        <span>
          <i className="swatch swatch-forecast" aria-hidden="true" />
          Forecast
        </span>
        {models.length > 0 ? <span className="legend-note">Model {models.join(", ")}</span> : null}
      </figcaption>
      <svg
        className="chart"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`Weekly demand and forecast for ${skill}`}
      >
        {yTicks.map((tick) => {
          const y = yAt(tick, yMax);
          return (
            <g key={tick}>
              <line className="grid" x1={PAD.left} x2={WIDTH - PAD.right} y1={y} y2={y} />
              <text x={PAD.left - 8} y={y + 4} textAnchor="end">
                {formatNumber(tick)}
              </text>
            </g>
          );
        })}
        {band ? <polygon className="band" points={band} /> : null}
        {demandPoints.length > 0 ? <polyline className="demand" points={demandPoints.join(" ")} /> : null}
        {forecastPoints.length > 0 ? <polyline className="forecast" points={forecastPoints.join(" ")} /> : null}
        {showDots
          ? rows.map((row, index) => {
              const cx = xAt(index, count);
              return (
                <g key={row.date}>
                  {row.demand !== null ? (
                    <circle className="dot-demand" cx={cx} cy={yAt(row.demand, yMax)} r={dotRadius} />
                  ) : null}
                  {row.forecast !== null ? (
                    <circle className="dot-forecast" cx={cx} cy={yAt(row.forecast, yMax)} r={dotRadius} />
                  ) : null}
                </g>
              );
            })
          : null}
        {tickIndexes(count).map((index) => {
          const row = rows[index];
          if (!row) return null;
          const anchor =
            count <= 1 ? "middle" : index === 0 ? "start" : index === count - 1 ? "end" : "middle";
          return (
            <text key={row.date} x={xAt(index, count)} y={HEIGHT - 10} textAnchor={anchor}>
              {shortWeek(row.date)}
            </text>
          );
        })}
      </svg>
      <div className="table-scroll">
      <table>
        <caption>Weekly demand and forecast for {skill}</caption>
        <thead>
          <tr>
            <th scope="col">Week</th>
            <th scope="col">Demand</th>
            <th scope="col">Forecast</th>
            <th scope="col">Lower</th>
            <th scope="col">Upper</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.date}>
              <td>{formatWeek(row.date)}</td>
              <td>{row.demand === null ? "—" : formatNumber(row.demand)}</td>
              <td>{row.forecast === null ? "—" : formatNumber(row.forecast)}</td>
              <td>{row.lower === null ? "—" : formatNumber(row.lower)}</td>
              <td>{row.upper === null ? "—" : formatNumber(row.upper)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </figure>
  );
}
