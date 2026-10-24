"use client";

import { useState, type ReactNode } from "react";

import type { AttendanceTrendDay, AttendanceWeekday } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { formatDelta, formatPct } from "./status";

/**
 * The attendance analytics charts.
 *
 * Hand-drawn SVG and flex boxes, like the dashboard's board
 * (`components/dashboard/analytics.tsx`): the shapes are a line and a set of bars,
 * and a charting library would be the heaviest thing on the page. Both are a SINGLE
 * series, so both use one hue (`chart-1`) and no legend — the card title names what
 * is plotted. Gridlines are solid hairlines in the border colour; marks are thin.
 *
 * Every value a tooltip shows is also reachable without hovering: the trend has a
 * table twin, and the weekday bars print their values beside the bars.
 */

type Tip = { x: number; y: number; content: ReactNode } | null;

/** One tooltip per chart, positioned over the hovered mark inside `[data-chart]`. */
function useChartTip() {
  const [tip, setTip] = useState<Tip>(null);
  const show = (event: React.SyntheticEvent<Element>, content: ReactNode) => {
    const target = event.currentTarget.getBoundingClientRect();
    const host = event.currentTarget.closest("[data-chart]")?.getBoundingClientRect();
    if (!host) return;
    setTip({ x: target.left - host.left + target.width / 2, y: target.top - host.top, content });
  };
  const node = tip ? (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-md"
      style={{ left: tip.x, top: tip.y - 8 }}
    >
      {tip.content}
    </div>
  ) : null;
  return { show, hide: () => setTip(null), node };
}

function useDateFormats() {
  // The page's own locale would need the i18n provider; these screens are English,
  // like the register board they sit beside.
  return {
    short: new Intl.DateTimeFormat("en-PK", { day: "numeric", month: "short" }),
    long: new Intl.DateTimeFormat("en-PK", { weekday: "short", day: "numeric", month: "short" }),
  };
}

const parse = (iso: string) => new Date(`${iso}T00:00:00`);

// ---------------------------------------------------------------------------
// Daily trend: one line over school days
// ---------------------------------------------------------------------------

/**
 * The rate on each school day in the range.
 *
 * SCHOOL DAYS ONLY, EVENLY SPACED. The API lists only dates with a submitted
 * register, and they are plotted side by side rather than on a calendar axis: on a
 * calendar axis every weekend would be a gap and every gap would read as a fall.
 *
 * The y-axis starts near the data, not at 0. A school's days live between roughly
 * 80% and 100%, and on a 0–100 axis a bad Monday would be a hairline. The floor is
 * labelled, so nobody mistakes the bottom of the plot for zero.
 */
export function TrendChart({ days }: { days: AttendanceTrendDay[] }) {
  const { show, hide, node } = useChartTip();
  const [active, setActive] = useState<number | null>(null);
  const dates = useDateFormats();

  const values = days.map((d) => d.percentage).filter((v): v is number => v != null);
  if (values.length === 0) return null;

  const low = Math.min(...values);
  const floor = Math.max(0, Math.min(90, Math.floor((low - 5) / 10) * 10));
  const span = 100 - floor;
  const ticks = [floor, Math.round(floor + span / 2), 100];

  const n = days.length;
  const x = (i: number) => (n === 1 ? 50 : 1.5 + (i / (n - 1)) * 97);
  const y = (v: number) => (1 - (v - floor) / span) * 100;

  // A day with no countable line (all excused) breaks the line rather than diving.
  let line = "";
  const areas: string[] = [];
  let run: [number, number][] = [];
  const flush = () => {
    if (run.length > 1) {
      const [first] = run;
      const last = run[run.length - 1]!;
      areas.push(
        `M${first![0]},100 ${run.map(([px, py]) => `L${px},${py}`).join(" ")} L${last[0]},100 Z`,
      );
    }
    run = [];
  };
  days.forEach((d, i) => {
    if (d.percentage == null) {
      flush();
      return;
    }
    const point: [number, number] = [x(i), y(d.percentage)];
    line += `${run.length === 0 ? "M" : "L"}${point[0].toFixed(2)},${point[1].toFixed(2)} `;
    run.push(point);
  });
  flush();

  const lastIndex = days.findLastIndex((d) => d.percentage != null);
  const marker = active ?? lastIndex;
  const markerDay = days[marker];
  const labelIndexes = n <= 2 ? [...Array(n).keys()] : [0, Math.floor((n - 1) / 2), n - 1];

  const describe = (d: AttendanceTrendDay) =>
    `${dates.long.format(parse(d.session_date))}: ${formatPct(d.percentage)}, ${d.absent} absent`;

  return (
    <div data-chart className="relative">
      <div className="relative ms-10 h-48" onMouseLeave={() => (hide(), setActive(null))}>
        {ticks.map((tick) => (
          <div
            key={tick}
            className="absolute inset-x-0 border-t border-border"
            style={{ top: `${y(tick)}%` }}
            aria-hidden
          >
            <span className="absolute -start-10 w-8 -translate-y-1/2 text-end text-[11px] tabular-nums text-muted-foreground">
              {tick}%
            </span>
          </div>
        ))}

        <svg
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          className="absolute inset-0 size-full overflow-visible"
          aria-hidden
        >
          {areas.map((d) => (
            <path key={d} d={d} className="fill-chart-1" fillOpacity={0.1} />
          ))}
          <path
            d={line}
            fill="none"
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
            strokeLinejoin="round"
            strokeLinecap="round"
            className="stroke-chart-1"
          />
        </svg>

        {active != null ? (
          <div
            className="pointer-events-none absolute inset-y-0 w-px bg-foreground/25"
            style={{ left: `${x(active)}%` }}
            aria-hidden
          />
        ) : null}
        {markerDay?.percentage != null ? (
          <span
            className="pointer-events-none absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-chart-1 ring-2 ring-card"
            style={{ left: `${x(marker)}%`, top: `${y(markerDay.percentage)}%` }}
            aria-hidden
          />
        ) : null}

        {/* The hit layer: each day owns the band from halfway to its left neighbour
            to halfway to its right one, so the pointer finds a date, not a 2px line. */}
        {days.map((d, i) => {
          const left = i === 0 ? 0 : (x(i - 1) + x(i)) / 2;
          const right = i === n - 1 ? 100 : (x(i) + x(i + 1)) / 2;
          const label = describe(d);
          const content = (
            <span className="flex flex-col gap-0.5">
              <span className="text-sm font-semibold tabular-nums">{formatPct(d.percentage)}</span>
              <span className="text-muted-foreground">
                {dates.long.format(parse(d.session_date))} · {d.absent} absent
              </span>
            </span>
          );
          return (
            <button
              key={d.session_date}
              type="button"
              aria-label={label}
              className="absolute inset-y-0 outline-none focus-visible:bg-foreground/5"
              style={{ left: `${left}%`, width: `${right - left}%` }}
              onMouseEnter={(e) => (setActive(i), show(e, content))}
              onFocus={(e) => (setActive(i), show(e, content))}
              onBlur={() => (hide(), setActive(null))}
            />
          );
        })}
        {node}
      </div>

      <div className="relative ms-10 mt-1.5 h-4 text-[11px] text-muted-foreground" aria-hidden>
        {labelIndexes.map((i) => (
          <span
            key={i}
            className={cn(
              "absolute whitespace-nowrap",
              n === 1 || (i !== 0 && i !== n - 1) ? "-translate-x-1/2" : i === n - 1 && "-translate-x-full",
            )}
            style={{ left: `${x(i)}%` }}
          >
            {dates.short.format(parse(days[i]!.session_date))}
          </span>
        ))}
      </div>

      <details className="mt-3 text-xs">
        <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
          View as table
        </summary>
        <div className="mt-2 max-h-56 overflow-y-auto rounded-md border border-border">
          <table className="w-full text-start">
            <thead className="sticky top-0 bg-muted text-muted-foreground">
              <tr>
                <th className="px-2 py-1.5 text-start font-medium">Date</th>
                <th className="px-2 py-1.5 text-end font-medium">Attendance</th>
                <th className="px-2 py-1.5 text-end font-medium">Absent</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {days.map((d) => (
                <tr key={d.session_date} className="border-t border-border">
                  <td className="px-2 py-1">{dates.long.format(parse(d.session_date))}</td>
                  <td className="px-2 py-1 text-end">{formatPct(d.percentage)}</td>
                  <td className="px-2 py-1 text-end">{d.absent}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Weekday pattern: one bar per day the school marks
// ---------------------------------------------------------------------------

const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/**
 * The rate on each day of the week, against the range's overall rate.
 *
 * Bars run 0–100% so their lengths are honest; the pattern a principal is looking
 * for — Mondays after a long weekend, the Saturday of a five-and-a-half-day week —
 * is a few points, so the difference from the overall rate is printed beside each
 * bar rather than left for the eye to measure. Days the school never marked (most
 * often Sunday) are left out rather than drawn as empty.
 */
export function WeekdayPattern({
  weekdays,
  overall,
}: {
  weekdays: AttendanceWeekday[];
  overall: number | null | undefined;
}) {
  const { show, hide, node } = useChartTip();
  const marked = weekdays.filter((w) => w.school_days > 0);
  if (marked.length === 0) return null;

  return (
    <div data-chart className="relative">
      <ul className="space-y-2.5" onMouseLeave={hide}>
        {marked.map((w) => {
          const name = WEEKDAY_NAMES[w.weekday - 1]!;
          const delta = w.percentage != null && overall != null ? w.percentage - overall : null;
          const text = `${name}s: ${formatPct(w.percentage)} over ${w.school_days} school day${
            w.school_days === 1 ? "" : "s"
          }, ${w.absent} absence${w.absent === 1 ? "" : "s"}`;
          return (
            <li
              key={w.weekday}
              className="grid grid-cols-[2.5rem_minmax(0,1fr)_3.25rem_4.5rem] items-center gap-2 text-sm"
            >
              <span className="text-muted-foreground">{name.slice(0, 3)}</span>
              <button
                type="button"
                aria-label={text}
                onMouseEnter={(e) => show(e, text)}
                onFocus={(e) => show(e, text)}
                onBlur={hide}
                className="block h-2.5 w-full rounded-e-[4px] bg-muted outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {w.percentage != null ? (
                  <span
                    className="block h-full rounded-e-[4px] bg-chart-1"
                    style={{ width: `${Math.max(0, Math.min(100, w.percentage))}%` }}
                  />
                ) : null}
              </button>
              <span className="text-end font-medium tabular-nums">{formatPct(w.percentage)}</span>
              <span
                className={cn(
                  "text-end text-xs tabular-nums text-muted-foreground",
                  delta != null && delta <= -2 && "font-medium text-foreground",
                )}
              >
                {delta == null ? "" : formatDelta(delta)}
              </span>
            </li>
          );
        })}
      </ul>
      {node}
    </div>
  );
}
