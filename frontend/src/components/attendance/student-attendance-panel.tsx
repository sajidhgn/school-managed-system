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
 * per-student table, so the two can never show a child differently.
 */
export function StudentAttendancePanel({ studentId }: { studentId: string }) {
  const query = useStudentAttendanceCalendar(studentId);
  const [picked, setPicked] = React.useState<number | null>(null);

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

  const calendar = query.data;
  const index = Math.min(picked ?? calendar.months.length - 1, calendar.months.length - 1);
  const month = calendar.months[index];
  if (!month) return null;

  const byDate = new Map(calendar.days.map((d) => [d.session_date, d]));
  const [year, monthNumber] = month.month.split("-").map(Number) as [number, number];
  const first = new Date(year, monthNumber - 1, 1);
  const length = new Date(year, monthNumber, 0).getDate();
  const lead = (first.getDay() + 6) % 7; // Monday-first rows
  const monthName = new Intl.DateTimeFormat("en-PK", { month: "long", year: "numeric" }).format(
    first,
  );
  const dayName = new Intl.DateTimeFormat("en-PK", { weekday: "short", day: "numeric", month: "short" });
  const headers = ["M", "T", "W", "T", "F", "S", "S"];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <RateFigure label={monthName} rate={month} />
        <RateFigure label="Academic year so far" rate={calendar.overall} />
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between gap-2">
          <Button
            variant="ghost"
            size="icon"
            disabled={index === 0}
            onClick={() => setPicked(index - 1)}
            aria-label="Previous month"
          >
            <ChevronLeft />
          </Button>
          <p className="text-sm font-medium" aria-live="polite">
            {monthName}
          </p>
          <Button
            variant="ghost"
            size="icon"
            disabled={index === calendar.months.length - 1}
            onClick={() => setPicked(index + 1)}
            aria-label="Next month"
          >
            <ChevronRight />
          </Button>
        </div>

        <div className="grid grid-cols-7 gap-1" role="grid" aria-label={`Attendance, ${monthName}`}>
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
              />
            );
          })}
        </div>
      </div>

      <Legend />
    </div>
  );
}

function RateFigure({ label, rate }: { label: string; rate: AttendanceRate }) {
  const { counts } = rate;
  return (
    <div className="rounded-lg border border-border p-3">
      <p className="truncate text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{formatPct(rate.percentage)}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {rate.counted === 0 && counts.excused === 0
          ? "No submitted registers"
          : `${counts.absent} absent · ${counts.late} late · ${counts.half_day} half · ${counts.excused} leave`}
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
}: {
  day: number;
  entry: StudentAttendanceCalendarDay | undefined;
  future: boolean;
  label: string;
  today: boolean;
}) {
  const status = entry?.register_state === "submitted" ? entry.status : null;
  const meta = status ? STATUS_META[status] : null;
  const description = meta
    ? meta.label
    : entry?.register_state === "draft"
      ? "Register open, not submitted"
      : future
        ? "Upcoming"
        : "No register";

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

function Legend() {
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
            {meta.label}
          </li>
        );
      })}
      <li className="flex items-center gap-1.5">
        <span className="size-4 rounded-sm border border-dashed border-muted-foreground/50" aria-hidden />
        Register open
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
