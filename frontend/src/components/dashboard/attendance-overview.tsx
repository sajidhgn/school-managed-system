"use client";

import type { Route } from "next";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  Minus,
} from "lucide-react";

import { useTranslations } from "@/components/providers/i18n-provider";
import type { AttendanceAnalytics, RegisterState, SchoolRead } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { MixBar } from "./analytics";

/**
 * The dashboard's attendance pair: the overall ratio, and every class ranked.
 *
 * Both read ONE response — `GET /attendance/analytics` with its defaults (the last
 * 30 days) — fetched by the page only for a viewer holding `attendance:read`. The
 * server bounds it: the campus for a principal, their own sections for a teacher, so
 * the same card is truthful for both without a branch here.
 *
 * THE HEADLINE IS THIS MONTH, NOT "THE LAST 30 DAYS". It is the number a principal
 * quotes in a staff meeting and compares with last month's; the server fixes it to
 * the calendar so it does not drift with anyone's date picker. Today and the year so
 * far sit beside it.
 *
 * Colour: the rate bars are one hue (`chart-1`, magnitude); register states use the
 * state colours with an icon and a screen-reader label, so nothing is colour alone.
 */
export function AttendanceOverview({
  data,
  schools,
}: {
  data: AttendanceAnalytics;
  schools: SchoolRead[];
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
      <OverviewCard data={data} />
      <ClassAttendanceCard data={data} schools={schools} />
    </div>
  );
}

function pct(value: number | null | undefined, digits = 1): string {
  return value == null ? "—" : `${value.toFixed(digits)}%`;
}

function fill(template: string, values: Record<string, string | number>): string {
  return Object.entries(values).reduce((s, [k, v]) => s.replace(`{${k}}`, String(v)), template);
}

function points(delta: number): string {
  return `${delta >= 0 ? "+" : "−"}${Math.abs(delta).toFixed(1)} pts`;
}

function OverviewCard({ data }: { data: AttendanceAnalytics }) {
  const { t } = useTranslations();
  const { headline } = data;
  const now = headline.this_month.percentage;
  const before = headline.previous_month.percentage;
  const delta = now != null && before != null ? now - before : null;
  const flat = delta != null && Math.abs(delta) < 0.1;
  const Icon = delta == null || flat ? Minus : delta > 0 ? ArrowUpRight : ArrowDownRight;

  const minis = [
    { label: t.dashboard.today, value: headline.today.percentage },
    { label: t.dashboard.lastMonth, value: before },
    { label: t.dashboard.academicYear, value: headline.year_to_date?.percentage ?? null },
  ];

  return (
    <section className="flex flex-col rounded-xl border border-border bg-card p-5">
      <h2 className="text-sm font-medium">{t.dashboard.attendanceOverview}</h2>
      <p className="mt-0.5 text-xs text-muted-foreground">{t.dashboard.attendanceOverviewHint}</p>

      <div className="mt-4">
        <p className="text-xs text-muted-foreground">{t.dashboard.thisMonth}</p>
        <p className="text-5xl font-semibold tracking-tight">{pct(now)}</p>
        <p
          className={cn(
            "mt-1 flex items-center gap-1 text-xs",
            delta == null || flat
              ? "text-muted-foreground"
              : delta > 0
                ? "text-success"
                : "text-destructive",
          )}
        >
          <Icon className="size-3.5" aria-hidden />
          {delta == null
            ? now == null
              ? t.dashboard.noRate
              : t.dashboard.noLastMonth
            : fill(t.dashboard.vsLastMonth, { delta: points(delta) })}
        </p>
      </div>

      <dl className="mt-4 grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-border bg-border">
        {minis.map((m) => (
          <div key={m.label} className="bg-card px-2.5 py-2">
            <dt className="truncate text-[11px] text-muted-foreground">{m.label}</dt>
            <dd className="text-base font-semibold">{pct(m.value)}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-4">
        <MixBar mix={headline.this_month.counts} label={t.dashboard.thisMonth} />
      </div>

      <Link
        href="/attendance/students"
        className="mt-auto inline-flex items-center gap-1 pt-4 text-sm font-medium text-primary hover:underline"
      >
        {t.dashboard.everyStudent}
        <ArrowRight className="size-3.5 rtl:rotate-180" aria-hidden />
      </Link>
    </section>
  );
}

const STATE_ICON: Record<RegisterState, { Icon: typeof CircleCheck; className: string }> = {
  submitted: { Icon: CircleCheck, className: "text-success" },
  draft: { Icon: CircleAlert, className: "text-muted-foreground" },
  not_started: { Icon: CircleDashed, className: "text-warning-foreground dark:text-warning" },
};

const SHOWN = 8;

function ClassAttendanceCard({ data, schools }: { data: AttendanceAnalytics; schools: SchoolRead[] }) {
  const { t } = useTranslations();
  const stateLabel: Record<RegisterState, string> = {
    submitted: t.dashboard.registerSubmitted,
    draft: t.dashboard.registerDraft,
    not_started: t.dashboard.registerNotStarted,
  };

  // Lowest first: the card's job is to say where to look. A section with no rate
  // yet goes last — "nobody marked it" is a different problem from "attendance is
  // low", and the state icon already flags it.
  const ranked = [...data.sections].sort((a, b) => {
    if (a.percentage == null) return b.percentage == null ? 0 : 1;
    if (b.percentage == null) return -1;
    return a.percentage - b.percentage;
  });
  const shown = ranked.slice(0, SHOWN);

  // An organization-level principal with no campus open sees every campus; "Grade 9
  // · A" then needs the campus code to mean one section.
  const campuses = new Set(data.sections.map((s) => s.school_id));
  const codes = new Map(schools.map((s) => [s.id, s.code ?? s.name]));
  const label = (s: (typeof data.sections)[number]) =>
    `${s.class_name} · ${s.section_name}${campuses.size > 1 ? ` (${codes.get(s.school_id) ?? "?"})` : ""}`;

  const atRisk = data.summary.at_risk_students;

  return (
    <section className="flex flex-col rounded-xl border border-border bg-card p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium">{t.dashboard.classAttendance}</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">{t.dashboard.classAttendanceHint}</p>
        </div>
        <Link
          href={"/attendance/analytics" as Route}
          className="inline-flex shrink-0 items-center gap-1 text-sm font-medium text-primary hover:underline"
        >
          {t.dashboard.allClasses}
          <ArrowRight className="size-3.5 rtl:rotate-180" aria-hidden />
        </Link>
      </div>

      {shown.length === 0 ? (
        <p className="mt-4 rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
          {t.dashboard.emptyChart}
        </p>
      ) : (
        <ul className="mt-4 space-y-2.5">
          {shown.map((s) => {
            const name = label(s);
            const delta =
              s.percentage != null && s.previous_percentage != null
                ? s.percentage - s.previous_percentage
                : null;
            const flat = delta != null && Math.abs(delta) < 0.1;
            const Trend = delta == null || flat ? Minus : delta > 0 ? ArrowUpRight : ArrowDownRight;
            const state = STATE_ICON[s.today_status];
            const trendText =
              delta == null ? "" : fill(t.dashboard.vsPrevious30, { delta: points(delta) });
            return (
              <li
                key={s.section_id}
                className="grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)_3.25rem_1rem_1rem] items-center gap-2 text-sm"
                title={[name, pct(s.percentage), trendText, stateLabel[s.today_status]]
                  .filter(Boolean)
                  .join(" · ")}
              >
                <span className="truncate text-muted-foreground">{name}</span>
                <span className="h-2.5 rounded-e-[4px] bg-muted" aria-hidden>
                  {s.percentage != null ? (
                    <span
                      className="block h-full rounded-e-[4px] bg-chart-1"
                      style={{ width: `${Math.max(0, Math.min(100, s.percentage))}%` }}
                    />
                  ) : null}
                </span>
                <span className="text-end font-medium tabular-nums">{pct(s.percentage)}</span>
                <span
                  className={cn(
                    "flex justify-center",
                    delta == null || flat
                      ? "text-muted-foreground"
                      : delta > 0
                        ? "text-success"
                        : "text-destructive",
                  )}
                >
                  <Trend className="size-3.5" aria-hidden />
                  {trendText ? <span className="sr-only">{trendText}</span> : null}
                </span>
                <span className={cn("flex justify-center", state.className)}>
                  <state.Icon className="size-3.5" aria-hidden />
                  <span className="sr-only">{stateLabel[s.today_status]}</span>
                </span>
              </li>
            );
          })}
        </ul>
      )}

      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-4 text-xs">
        <Link
          href={"/attendance/analytics" as Route}
          className={cn(
            "inline-flex items-center gap-1.5 hover:underline",
            atRisk > 0 ? "font-medium text-foreground" : "text-muted-foreground",
          )}
        >
          {atRisk > 0 ? (
            <AlertTriangle className="size-3.5 text-warning-foreground dark:text-warning" aria-hidden />
          ) : null}
          {fill(atRisk > 0 ? t.dashboard.atRiskCount : t.dashboard.noneAtRisk, {
            count: atRisk,
            threshold: data.threshold,
          })}
        </Link>
        {ranked.length > SHOWN ? (
          <span className="text-muted-foreground">
            {fill(t.dashboard.moreSections, { count: ranked.length - SHOWN })}
          </span>
        ) : null}
      </div>
    </section>
  );
}
