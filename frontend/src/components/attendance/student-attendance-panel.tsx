"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Can } from "@/components/auth/can";
import { ErrorState } from "@/components/data-states";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/misc";
import { useStudentAttendanceCalendar } from "@/hooks/use-attendance";
import {
  PERMISSIONS,
  type AttendanceRate,
  type AttendanceStatus,
  type StudentAttendanceCalendar,
  type StudentAttendanceCalendarDay,
} from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { STATUS_META, STATUS_ORDER, formatPct } from "./status";

/**
 * One child's attendance, a month at a time.
 *
 * ONE REQUEST FOR THE WHOLE YEAR. The calendar endpoint returns every whole-day
 * register line from the start of the academic year, plus a rate per month computed
 * on the server under the module's rules — so paging between months is instant and
 * the rate beside each month is the server's, not arithmetic redone here.
 *
 * Each day carries its status as a colour AND a letter (P, A, L, ½, E) and an
 * accessible label; a day whose register is still a draft is outlined and says so,
 * because its pre-filled "present" has not been asserted by anyone.
 *
 * Used inline on the student's profile and inside `StudentAttendanceDialog` from the
 * per-student table, so the two can never show a child differently. The parent
 * portal renders the same `AttendanceCalendarView`, with its own translated labels.
 */
export function StudentAttendancePanel({ studentId }: { studentId: string }) {
  const query = useStudentAttendanceCalendar(studentId);

  if (query.isPending) {
    return (
      <div className="space-y-3" aria-busy>
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-56 w-full" />
      </div>
    );
  }
  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} className="py-8" />;
  }

  return <AttendanceCalendarView calendar={query.data} />;
}

/**
 * Every word the calendar prints, so a caller can supply another language.
 *
 * Plain strings with `{placeholders}` rather than functions: the parent portal hands
 * these from a Server Component to this Client Component, and only data crosses.
 */
export interface AttendanceCalendarLabels {
  /** BCP 47 locale for month and day names. */
  locale: string;
  yearSoFar: string;
  noRegisters: string;
  /** `{absent}`, `{late}`, `{half}` and `{leave}` are replaced with counts. */
  breakdown: string;
  previousMonth: string;
  nextMonth: string;
  /** Prefix of the grid's accessible name, followed by the month. */
  gridLabel: string;
  registerOpen: string;
  registerOpenDay: string;
  upcoming: string;
  noRegister: string;
  /** Monday first. */
  weekdays: string[];
  status: Record<AttendanceStatus, string>;
}

export const ATTENDANCE_CALENDAR_LABELS: AttendanceCalendarLabels = {
  locale: "en-PK",
  yearSoFar: "Academic year so far",
  noRegisters: "No submitted registers",
  breakdown: "{absent} absent · {late} late · {half} half · {leave} leave",
  previousMonth: "Previous month",
  nextMonth: "Next month",
  gridLabel: "Attendance",
  registerOpen: "Register open",
  registerOpenDay: "Register open, not submitted",
  upcoming: "Upcoming",
  noRegister: "No register",
  weekdays: ["M", "T", "W", "T", "F", "S", "S"],
  status: Object.fromEntries(
    STATUS_ORDER.map((status) => [status, STATUS_META[status].label]),
  ) as Record<AttendanceStatus, string>,
};

/** The calendar itself, given a year's data. Pages months locally. */
export function AttendanceCalendarView({
  calendar,
  labels = ATTENDANCE_CALENDAR_LABELS,
}: {
  calendar: StudentAttendanceCalendar;
  labels?: AttendanceCalendarLabels;
}) {
  const [picked, setPicked] = React.useState<number | null>(null);
  const index = Math.min(picked ?? calendar.months.length - 1, calendar.months.length - 1);
  const month = calendar.months[index];
  if (!month) return null;

  const byDate = new Map(calendar.days.map((d) => [d.session_date, d]));
  const [year, monthNumber] = month.month.split("-").map(Number) as [number, number];
  const first = new Date(year, monthNumber - 1, 1);
  const length = new Date(year, monthNumber, 0).getDate();
  const lead = (first.getDay() + 6) % 7; // Monday-first rows
  const monthName = new Intl.DateTimeFormat(labels.locale, { month: "long", year: "numeric" }).format(
    first,
  );
  const dayName = new Intl.DateTimeFormat(labels.locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
  const headers = labels.weekdays;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <RateFigure label={monthName} rate={month} labels={labels} />
        <RateFigure label={labels.yearSoFar} rate={calendar.overall} labels={labels} />
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between gap-2">
          <Button
            variant="ghost"
            size="icon"
            disabled={index === 0}
            onClick={() => setPicked(index - 1)}
            aria-label={labels.previousMonth}
          >
            <ChevronLeft className="rtl:rotate-180" />
          </Button>
          <p className="text-sm font-medium" aria-live="polite">
            {monthName}
          </p>
          <Button
            variant="ghost"
            size="icon"
            disabled={index === calendar.months.length - 1}
            onClick={() => setPicked(index + 1)}
            aria-label={labels.nextMonth}
          >
            <ChevronRight className="rtl:rotate-180" />
          </Button>
        </div>

        <div
          className="grid grid-cols-7 gap-1"
          role="grid"
          aria-label={`${labels.gridLabel}, ${monthName}`}
        >
          {headers.map((h, i) => (
            <div key={`h${i}`} className="pb-1 text-center text-[11px] text-muted-foreground" aria-hidden>
              {h}
            </div>
          ))}
          {Array.from({ length: lead }, (_, i) => (
            <div key={`b${i}`} aria-hidden />
          ))}
          {Array.from({ length: length }, (_, i) => {
            const date = new Date(year, monthNumber - 1, i + 1);
            const iso = `${month.month}-${String(i + 1).padStart(2, "0")}`;
            return (
              <DayCell
                key={iso}
                day={i + 1}
                entry={byDate.get(iso)}
                future={iso > calendar.today}
                label={dayName.format(date)}
                today={iso === calendar.today}
                labels={labels}
              />
            );
          })}
        </div>
      </div>

      <Legend labels={labels} />
    </div>
  );
}

function RateFigure({
  label,
  rate,
  labels,
}: {
  label: string;
  rate: AttendanceRate;
  labels: AttendanceCalendarLabels;
}) {
  const { counts } = rate;
  return (
    <div className="rounded-lg border border-border p-3">
      <p className="truncate text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{formatPct(rate.percentage)}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {rate.counted === 0 && counts.excused === 0
          ? labels.noRegisters
          : labels.breakdown
              .replace("{absent}", String(counts.absent))
              .replace("{late}", String(counts.late))
              .replace("{half}", String(counts.half_day))
              .replace("{leave}", String(counts.excused))}
      </p>
    </div>
  );
}

function DayCell({
  day,
  entry,
  future,
  label,
  today,
  labels,
}: {
  day: number;
  entry: StudentAttendanceCalendarDay | undefined;
  future: boolean;
  label: string;
  today: boolean;
  labels: AttendanceCalendarLabels;
}) {
  const status = entry?.register_state === "submitted" ? entry.status : null;
  const meta = status ? STATUS_META[status] : null;
  const description = status
    ? labels.status[status]
    : entry?.register_state === "draft"
      ? labels.registerOpenDay
      : future
        ? labels.upcoming
        : labels.noRegister;

  return (
    <div
      role="gridcell"
      aria-label={`${label}: ${description}`}
      title={`${label}: ${description}`}
      className={cn(
        "flex aspect-square flex-col items-center justify-center rounded-md text-xs",
        meta ? meta.cell : "text-muted-foreground",
        entry?.register_state === "draft" && "border border-dashed border-muted-foreground/50",
        future && "opacity-40",
        today && "ring-2 ring-foreground/60 ring-offset-1 ring-offset-card",
      )}
    >
      <span className={cn("leading-none", meta && "text-[10px] text-muted-foreground")}>{day}</span>
      {meta ? <span className="mt-0.5 text-sm font-semibold leading-none">{meta.short}</span> : null}
    </div>
  );
}

function Legend({ labels }: { labels: AttendanceCalendarLabels }) {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
      {STATUS_ORDER.map((status) => {
        const meta = STATUS_META[status];
        return (
          <li key={status} className="flex items-center gap-1.5">
            <span
              className={cn("grid size-4 place-items-center rounded-sm text-[10px] font-semibold text-foreground", meta.cell)}
              aria-hidden
            >
              {meta.short}
            </span>
            {labels.status[status]}
          </li>
        );
      })}
      <li className="flex items-center gap-1.5">
        <span className="size-4 rounded-sm border border-dashed border-muted-foreground/50" aria-hidden />
        {labels.registerOpen}
      </li>
    </ul>
  );
}

/** The drill-down from a table row: the panel, in a dialog, with a way to the profile. */
export function StudentAttendanceDialog({
  student,
  onClose,
}: {
  student: { id: string; name: string; detail?: string } | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={student !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{student?.name ?? "Attendance"}</DialogTitle>
          <DialogDescription>
            {student?.detail ? `${student.detail} · ` : ""}Submitted whole-day registers only.
          </DialogDescription>
        </DialogHeader>
        {student ? <StudentAttendancePanel studentId={student.id} /> : null}
        {student ? (
          <DialogFooter>
            <Can permission={PERMISSIONS.studentRead}>
              <Button asChild variant="outline">
                <Link href={`/students/${student.id}`}>Open profile</Link>
              </Button>
            </Can>
          </DialogFooter>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
