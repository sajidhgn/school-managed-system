"use client";

import * as React from "react";
import type { Route } from "next";
import Link from "next/link";
import { ArrowDown, ArrowUp, ArrowUpDown, CalendarDays, Download, Flame } from "lucide-react";

import { AttendanceTabs } from "@/components/attendance/attendance-tabs";
import { TrendChart, WeekdayPattern } from "@/components/attendance/charts";
import {
  RateMeter,
  RegisterStateBadge,
  TrendDelta,
  deltaPoints,
  downloadCsv,
  formatPct,
  shiftIso,
  todayIso,
} from "@/components/attendance/status";
import { StudentAttendanceDialog } from "@/components/attendance/student-attendance-panel";
import { EmptyState, ErrorState, TableCardSkeleton } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAttendanceAnalytics } from "@/hooks/use-attendance";
import { useCurrentAcademicYear, useTerms } from "@/hooks/use-calendar";
import type {
  AttendanceAnalytics,
  SectionAttendanceAnalytics,
  TermRead,
} from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * The class-by-class attendance view.
 *
 * ONE FILTER ROW SCOPES EVERYTHING BELOW IT. The range, the class and the at-risk
 * threshold go to the server as one request, and every tile, chart and table on the
 * page is the same slice — so the numbers always agree with each other. While a new
 * slice loads, the old one stays on screen, dimmed, rather than collapsing to
 * skeletons and jumping back.
 *
 * WHAT THE NUMBERS ARE (stated on the page too, because they are proxies):
 *   * rates count SUBMITTED WHOLE-DAY registers, excused out of the denominator,
 *     half days at 0.5 — the module's rules, computed on the server;
 *   * a "school day" is a date someone submitted a register on — there is no
 *     holiday calendar — so coverage flags sections that fell behind their
 *     colleagues, not a campus that stopped marking;
 *   * the headline (today / this month / last month / year) is fixed to the
 *     calendar and does not move with the range.
 */

type Preset = "7" | "30" | "90" | "term" | "custom";

const THRESHOLDS = [60, 70, 75, 80, 85, 90];

type SortKey = "class" | "rate" | "change" | "coverage" | "at_risk";

/** The term containing today, else the most recent one that has started. */
function currentTerm(terms: TermRead[] | undefined, today: string): TermRead | null {
  if (!terms?.length) return null;
  const started = terms.filter((t) => t.start_date <= today);
  return (
    started.find((t) => t.end_date >= today) ??
    started.sort((a, b) => b.start_date.localeCompare(a.start_date))[0] ??
    null
  );
}

export function AnalyticsView({ canReadCalendar }: { canReadCalendar: boolean }) {
  const today = todayIso();
  const [preset, setPreset] = React.useState<Preset>("30");
  const [custom, setCustom] = React.useState({ from: shiftIso(today, -29), to: today });
  const [classId, setClassId] = React.useState<string>("");
  const [threshold, setThreshold] = React.useState(75);
  const [drill, setDrill] = React.useState<{ id: string; name: string; detail?: string } | null>(
    null,
  );

  // The term list is optional: without `calendar:read`, or with no calendar set up,
  // "This term" simply is not offered.
  const year = useCurrentAcademicYear();
  const terms = useTerms(canReadCalendar ? (year.data?.id ?? null) : null);
  const term = canReadCalendar ? currentTerm(terms.data, today) : null;

  const range = React.useMemo(() => {
    if (preset === "custom") return { from_date: custom.from, to_date: custom.to };
    if (preset === "term" && term) {
      return { from_date: term.start_date, to_date: term.end_date < today ? term.end_date : today };
    }
    const days = preset === "7" ? 7 : preset === "90" ? 90 : 30;
    return { from_date: shiftIso(today, -(days - 1)), to_date: today };
  }, [preset, custom, term, today]);

  const query = useAttendanceAnalytics({
    ...range,
    class_id: classId || null,
    threshold,
  });
  const data = query.data;
  const reloading = query.isFetching && query.isPlaceholderData;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Attendance analytics"
        description="How each class is attending, whether registers are being marked, and who needs a call home."
        actions={
          data && data.sections.length > 0 ? (
            <Button variant="outline" onClick={() => exportSections(data)}>
              <Download />
              Export CSV
            </Button>
          ) : null
        }
      />
      <AttendanceTabs />

      {/* --- Filters: one row, scoping everything below ------------------- */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="range-preset" className="text-xs">
            Range
          </Label>
          <NativeSelect
            id="range-preset"
            value={preset}
            onChange={(e) => setPreset(e.target.value as Preset)}
            className="w-40"
          >
            <option value="7">Last 7 days</option>
            <option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option>
            {term ? <option value="term">This term ({term.name})</option> : null}
            <option value="custom">Custom range</option>
          </NativeSelect>
        </div>
        {preset === "custom" ? (
          <>
            <div className="space-y-1">
              <Label htmlFor="range-from" className="text-xs">
                From
              </Label>
              <Input
                id="range-from"
                type="date"
                value={custom.from}
                max={custom.to}
                onChange={(e) => e.target.value && setCustom((c) => ({ ...c, from: e.target.value }))}
                className="w-40"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="range-to" className="text-xs">
                To
              </Label>
              <Input
                id="range-to"
                type="date"
                value={custom.to}
                min={custom.from}
                max={today}
                onChange={(e) => e.target.value && setCustom((c) => ({ ...c, to: e.target.value }))}
                className="w-40"
              />
            </div>
          </>
        ) : null}
        <div className="space-y-1">
          <Label htmlFor="class-filter" className="text-xs">
            Class
          </Label>
          <NativeSelect
            id="class-filter"
            value={classId}
            onChange={(e) => setClassId(e.target.value)}
            className="w-44"
          >
            <option value="">All classes</option>
            {data?.classes.map((c) => (
              <option key={c.class_id} value={c.class_id}>
                {c.class_name}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1">
          <Label htmlFor="threshold" className="text-xs">
            At risk below
          </Label>
          <NativeSelect
            id="threshold"
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-28"
          >
            {THRESHOLDS.map((t) => (
              <option key={t} value={t}>
                {t}%
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>

      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : !data ? (
        <TableCardSkeleton columns={5} rows={6} />
      ) : (
        <div className={cn("space-y-6 transition-opacity", reloading && "opacity-60")} aria-busy={reloading}>
          <Headline data={data} />
          <KpiTiles data={data} />

          {data.summary.counted === 0 ? (
            <Card>
              <EmptyState
                icon={CalendarDays}
                title="No submitted registers in this range"
                description="Rates appear once whole-day registers are submitted. Drafts and lesson registers are not counted."
              />
            </Card>
          ) : (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <Card>
                <CardHeader>
                  <CardTitle>Daily attendance</CardTitle>
                  <CardDescription>Each school day in the range, as a percentage.</CardDescription>
                </CardHeader>
                <CardContent>
                  <TrendChart days={data.days} />
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>By day of the week</CardTitle>
                  <CardDescription>Difference from the overall rate for the range.</CardDescription>
                </CardHeader>
                <CardContent>
                  <WeekdayPattern weekdays={data.weekdays} overall={data.summary.percentage} />
                </CardContent>
              </Card>
            </div>
          )}

          <SectionsTable data={data} />
          <AtRisk data={data} onOpen={setDrill} />
        </div>
      )}

      <StudentAttendanceDialog student={drill} onClose={() => setDrill(null)} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Headline and KPI tiles
// ---------------------------------------------------------------------------

function Headline({ data }: { data: AttendanceAnalytics }) {
  const { headline } = data;
  const items = [
    { label: "Today", rate: headline.today.percentage },
    { label: "This month", rate: headline.this_month.percentage },
    { label: "Last month", rate: headline.previous_month.percentage },
    { label: "Academic year", rate: headline.year_to_date?.percentage ?? null },
  ];
  return (
    <section aria-label="Attendance at a glance" className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-4">
      {items.map((item) => (
        <div key={item.label} className="bg-card px-4 py-3">
          <p className="text-xs text-muted-foreground">{item.label}</p>
          <p className="mt-0.5 text-xl font-semibold">{formatPct(item.rate)}</p>
          {item.label === "This month" ? (
            <TrendDelta
              now={headline.this_month.percentage}
              before={headline.previous_month.percentage}
              suffix="vs last month"
            />
          ) : null}
        </div>
      ))}
    </section>
  );
}

function KpiTiles({ data }: { data: AttendanceAnalytics }) {
  const { summary } = data;
  const days =
    (new Date(`${data.to_date}T00:00:00`).getTime() - new Date(`${data.from_date}T00:00:00`).getTime()) /
      86_400_000 +
    1;
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Tile label="Attendance rate" value={formatPct(summary.percentage)}>
        <TrendDelta
          now={summary.percentage}
          before={summary.previous_percentage}
          suffix={`vs previous ${days} days`}
        />
      </Tile>
      <Tile label="School days" value={String(summary.school_days)}>
        Days on which at least one register was submitted.
      </Tile>
      <Tile label="Marking coverage" value={formatPct(summary.coverage_percentage, 0)}>
        {summary.registers_expected > 0
          ? `${summary.registers_submitted} of ${summary.registers_expected} registers submitted.`
          : "Nothing to measure against yet."}
      </Tile>
      <Tile label="Students at risk" value={String(summary.at_risk_students)}>
        Below {data.threshold}% with {data.min_sessions}+ registers counted.
      </Tile>
    </div>
  );
}

function Tile({ label, value, children }: { label: string; value: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="py-4">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="mt-1 text-3xl font-semibold">{value}</p>
        <div className="mt-2 text-xs text-muted-foreground">{children}</div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

const SORTERS: Record<SortKey, (a: SectionAttendanceAnalytics, b: SectionAttendanceAnalytics) => number> = {
  // The server's order is the school's order (level, then section); keep it.
  class: () => 0,
  rate: (a, b) => nullsLast(a.percentage, b.percentage),
  change: (a, b) =>
    nullsLast(
      deltaPoints(a.percentage, a.previous_percentage),
      deltaPoints(b.percentage, b.previous_percentage),
    ),
  coverage: (a, b) => nullsLast(a.coverage_percentage, b.coverage_percentage),
  at_risk: (a, b) => a.at_risk_students - b.at_risk_students,
};

function nullsLast(a: number | null | undefined, b: number | null | undefined): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return a - b;
}

function SectionsTable({ data }: { data: AttendanceAnalytics }) {
  const [sort, setSort] = React.useState<{ key: SortKey; desc: boolean }>({ key: "class", desc: false });
  const rows = React.useMemo(() => {
    const sorted = [...data.sections].sort(SORTERS[sort.key]);
    // Nulls stay last whichever way the column is sorted: "no rate" is not the
    // worst rate, and reversing must not float it to the top.
    if (sort.desc && sort.key !== "class") {
      const known = sorted.filter((r) => sortValue(r, sort.key) != null).reverse();
      return [...known, ...sorted.filter((r) => sortValue(r, sort.key) == null)];
    }
    return sort.desc ? sorted.reverse() : sorted;
  }, [data.sections, sort]);

  const header = (key: SortKey, label: string, className?: string) => {
    const active = sort.key === key;
    const Icon = !active ? ArrowUpDown : sort.desc ? ArrowDown : ArrowUp;
    return (
      <TableHead
        className={className}
        aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}
      >
        <button
          type="button"
          className="inline-flex items-center gap-1 hover:text-foreground"
          onClick={() => setSort({ key, desc: active ? !sort.desc : key === "at_risk" })}
        >
          {label}
          <Icon className="size-3.5" aria-hidden />
        </button>
      </TableHead>
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sections</CardTitle>
        <CardDescription>
          {data.from_date} to {data.to_date}. Change is against {data.previous_from_date} to{" "}
          {data.previous_to_date}. Coverage counts registers submitted on the{" "}
          {data.summary.school_days} school day{data.summary.school_days === 1 ? "" : "s"}.
        </CardDescription>
      </CardHeader>
      <CardContent className="px-0">
        {rows.length === 0 ? (
          <EmptyState title="No sections to show" description="Create a class and a section, or pick another class." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                {header("class", "Section")}
                <TableHead>Today</TableHead>
                {header("rate", "Attendance", "min-w-44")}
                {header("change", "Change")}
                {header("coverage", "Coverage")}
                <TableHead className="text-end">Absences</TableHead>
                {header("at_risk", "At risk", "text-end")}
                <TableHead className="text-end">Students</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => {
                const label = `${row.class_name} · ${row.section_name}`;
                return (
                  <TableRow key={row.section_id}>
                    <TableCell>
                      <Link
                        href={`/attendance/students?section_id=${row.section_id}` as Route}
                        className="font-medium hover:underline"
                      >
                        {label}
                      </Link>
                      <p className="text-xs text-muted-foreground">
                        {row.class_teacher_name ?? "No class teacher"}
                      </p>
                    </TableCell>
                    <TableCell>
                      <RegisterStateBadge state={row.today_status} />
                    </TableCell>
                    <TableCell>
                      <RateMeter value={row.percentage} label={label} />
                    </TableCell>
                    <TableCell>
                      <TrendDelta now={row.percentage} before={row.previous_percentage} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <span className="tabular-nums">{formatPct(row.coverage_percentage, 0)}</span>
                      <span className="ms-1.5 text-xs text-muted-foreground tabular-nums">
                        {row.registers_submitted}/{data.summary.school_days}
                      </span>
                      {row.registers_draft > 0 ? (
                        <Badge variant="neutral" className="ms-1.5" title="Registers opened but never submitted">
                          {row.registers_draft} draft{row.registers_draft === 1 ? "" : "s"}
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-end tabular-nums">{row.counts.absent}</TableCell>
                    <TableCell className="text-end tabular-nums">
                      {row.at_risk_students > 0 ? (
                        <span className="font-medium">{row.at_risk_students}</span>
                      ) : (
                        <span className="text-muted-foreground">0</span>
                      )}
                    </TableCell>
                    <TableCell className="text-end tabular-nums text-muted-foreground">
                      {row.students_on_roll}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function sortValue(row: SectionAttendanceAnalytics, key: SortKey): number | null {
  if (key === "rate") return row.percentage ?? null;
  if (key === "change") return deltaPoints(row.percentage, row.previous_percentage);
  if (key === "coverage") return row.coverage_percentage ?? null;
  if (key === "at_risk") return row.at_risk_students;
  return 0;
}

function exportSections(data: AttendanceAnalytics) {
  const header = [
    "Class",
    "Section",
    "Class teacher",
    "Students on roll",
    "Attendance %",
    "Previous period %",
    "Change (pts)",
    "Present",
    "Late",
    "Half day",
    "Absent",
    "Excused",
    "Registers submitted",
    "Registers in draft",
    "School days",
    "Coverage %",
    "Today",
    "At risk",
  ];
  const rows = data.sections.map((r) => {
    const delta = deltaPoints(r.percentage, r.previous_percentage);
    return [
      r.class_name,
      r.section_name,
      r.class_teacher_name ?? "",
      r.students_on_roll,
      r.percentage ?? "",
      r.previous_percentage ?? "",
      delta == null ? "" : delta.toFixed(2),
      r.counts.present,
      r.counts.late,
      r.counts.half_day,
      r.counts.absent,
      r.counts.excused,
      r.registers_submitted,
      r.registers_draft,
      data.summary.school_days,
      r.coverage_percentage ?? "",
      r.today_status,
      r.at_risk_students,
    ];
  });
  downloadCsv(`attendance-${data.from_date}-to-${data.to_date}.csv`, [header, ...rows]);
}

// ---------------------------------------------------------------------------
// At-risk students
// ---------------------------------------------------------------------------

function AtRisk({
  data,
  onOpen,
}: {
  data: AttendanceAnalytics;
  onOpen: (student: { id: string; name: string; detail?: string }) => void;
}) {
  const total = data.summary.at_risk_students;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Students at risk</CardTitle>
        <CardDescription>
          Below {data.threshold}% over the range, with at least {data.min_sessions} registers counted
          so one bad day does not flag a child. Lowest first.
          {total > data.at_risk.length ? ` Showing the ${data.at_risk.length} lowest of ${total}.` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="px-0">
        {data.at_risk.length === 0 ? (
          <EmptyState title="Nobody below the threshold" description="No student in this range is under it with enough registers counted." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Student</TableHead>
                <TableHead>Class</TableHead>
                <TableHead className="text-end">Attendance</TableHead>
                <TableHead className="text-end">Absent</TableHead>
                <TableHead>Current run</TableHead>
                <TableHead className="w-28" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.at_risk.map((s) => {
                const placement = s.class_name ? `${s.class_name} · ${s.section_name}` : "Unplaced";
                return (
                  <TableRow key={s.student_id}>
                    <TableCell>
                      <Link href={`/students/${s.student_id}`} className="font-medium hover:underline">
                        {s.full_name}
                      </Link>
                      <p className="text-xs text-muted-foreground">{s.admission_number}</p>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {placement}
                      {s.roll_number ? (
                        <span className="ms-1.5 text-xs text-muted-foreground">Roll {s.roll_number}</span>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-end font-medium tabular-nums">
                      {formatPct(s.percentage)}
                    </TableCell>
                    <TableCell className="text-end tabular-nums">
                      {s.absent}
                      <span className="text-muted-foreground"> / {s.counted_sessions}</span>
                    </TableCell>
                    <TableCell>
                      {s.absence_streak >= 2 ? (
                        <Badge variant="destructive">
                          <Flame className="size-3" aria-hidden />
                          Absent {s.absence_streak} days running
                        </Badge>
                      ) : s.absence_streak === 1 ? (
                        <span className="text-xs text-muted-foreground">Absent last register</span>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-end">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => onOpen({ id: s.student_id, name: s.full_name, detail: placement })}
                      >
                        Calendar
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

