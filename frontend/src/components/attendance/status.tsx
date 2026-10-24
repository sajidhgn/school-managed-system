import {
  ArrowDownRight,
  ArrowUpRight,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleMinus,
  CircleX,
  Clock,
  Contrast,
  Minus,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { AttendanceStatus, RegisterState } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * The attendance vocabulary, stated once for every analytics screen.
 *
 * Status colour is STATE colour (success / warning / destructive), and every use of
 * it travels with an icon and a word — a reader who cannot tell the green from the
 * red still reads "Absent". The tints match the dashboard's register mix
 * (`components/dashboard/analytics.tsx`), so a colour means the same thing on every
 * screen that shows attendance.
 */
export const STATUS_META: Record<
  AttendanceStatus,
  {
    label: string;
    /** One character for a calendar cell, where a word will not fit. */
    short: string;
    Icon: typeof CircleCheck;
    /** A light wash for a cell, with ordinary ink on it. */
    cell: string;
    /** A solid swatch for a legend dot or bar. */
    swatch: string;
    badge: "success" | "warning" | "destructive" | "neutral";
  }
> = {
  present: {
    label: "Present",
    short: "P",
    Icon: CircleCheck,
    cell: "bg-success/15",
    swatch: "bg-success",
    badge: "success",
  },
  late: {
    label: "Late",
    short: "L",
    Icon: Clock,
    cell: "bg-warning/25",
    swatch: "bg-warning",
    badge: "warning",
  },
  half_day: {
    label: "Half day",
    short: "½",
    Icon: Contrast,
    cell: "bg-warning/12",
    swatch: "bg-warning/50",
    badge: "warning",
  },
  absent: {
    label: "Absent",
    short: "A",
    Icon: CircleX,
    cell: "bg-destructive/15",
    swatch: "bg-destructive",
    badge: "destructive",
  },
  excused: {
    // "Leave" is the word schools here use for an authorised absence; the API calls
    // it `excused`. Both appear so neither audience has to translate.
    label: "Leave (excused)",
    short: "E",
    Icon: CircleMinus,
    cell: "bg-muted",
    swatch: "bg-muted-foreground/40",
    badge: "neutral",
  },
};

/** Display order: in the building first, then out of it. */
export const STATUS_ORDER: AttendanceStatus[] = ["present", "late", "half_day", "absent", "excused"];

export function AttendanceStatusBadge({ status }: { status: AttendanceStatus }) {
  const meta = STATUS_META[status];
  return (
    <Badge variant={meta.badge}>
      <meta.Icon className="size-3" aria-hidden />
      {meta.label}
    </Badge>
  );
}

/**
 * A section's register for today. The same three words and treatments as the
 * register board on `/attendance`, so the two screens read as one system: "Not
 * started" is the warning, because it is the state somebody has to go and chase.
 */
export const REGISTER_META: Record<
  RegisterState,
  { label: string; Icon: typeof CircleCheck; badge: "success" | "warning" | "neutral" }
> = {
  submitted: { label: "Submitted", Icon: CircleCheck, badge: "success" },
  draft: { label: "In progress", Icon: CircleAlert, badge: "neutral" },
  not_started: { label: "Not started", Icon: CircleDashed, badge: "warning" },
};

export function RegisterStateBadge({ state }: { state: RegisterState }) {
  const meta = REGISTER_META[state];
  return (
    <Badge variant={meta.badge}>
      <meta.Icon className="size-3" aria-hidden />
      {meta.label}
    </Badge>
  );
}

/**
 * One child's line for today.
 *
 * THREE DIFFERENT FACTS, NEVER COLLAPSED. "Present" means a submitted register says
 * so. "Register open" means a teacher has started one but not asserted it — its lines
 * are pre-filled present, which is exactly why the API withholds them. "Not marked"
 * means nobody has opened a register that includes this child today. Showing either
 * of the last two as "Present" is the mistake the register table exists to prevent.
 */
export function TodayBadge({
  register,
  status,
}: {
  register: RegisterState;
  status: AttendanceStatus | null | undefined;
}) {
  if (register === "submitted" && status) return <AttendanceStatusBadge status={status} />;
  if (register === "draft") {
    return (
      <Badge variant="neutral">
        <CircleAlert className="size-3" aria-hidden />
        Register open
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-muted-foreground">
      <CircleDashed className="size-3" aria-hidden />
      Not marked
    </Badge>
  );
}

/** `91.4%`, or an em dash for "no rate" — never `0%`, which would be a claim. */
export function formatPct(value: number | null | undefined, digits = 1): string {
  return value == null ? "—" : `${value.toFixed(digits)}%`;
}

/** Percentage-point change, or null when either side has no rate. */
export function deltaPoints(
  now: number | null | undefined,
  before: number | null | undefined,
): number | null {
  return now == null || before == null ? null : now - before;
}

/** `+2.4 pts` / `−1.0 pts`, with a true minus sign. */
export function formatDelta(delta: number): string {
  return `${delta >= 0 ? "+" : "−"}${Math.abs(delta).toFixed(1)} pts`;
}

/**
 * A change in attendance rate: arrow, signed points, and — because up is good here —
 * green for up and red for down. Below a tenth of a point it is "flat", so rounding
 * noise never paints a section red.
 */
export function TrendDelta({
  now,
  before,
  suffix,
  className,
  compact = false,
}: {
  now: number | null | undefined;
  before: number | null | undefined;
  /** e.g. "vs previous 30 days"; omitted in tables, where the header says it. */
  suffix?: string;
  className?: string;
  /** Icon only, with the figure for screen readers and the tooltip. */
  compact?: boolean;
}) {
  const delta = deltaPoints(now, before);
  if (delta == null) {
    return (
      <span className={cn("text-xs text-muted-foreground", className)}>
        {compact ? <span aria-label="No earlier data">—</span> : "No earlier data"}
      </span>
    );
  }
  const flat = Math.abs(delta) < 0.1;
  const Icon = flat ? Minus : delta > 0 ? ArrowUpRight : ArrowDownRight;
  const text = `${formatDelta(delta)}${suffix ? ` ${suffix}` : ""}`;
  return (
    <span
      title={text}
      className={cn(
        "inline-flex items-center gap-1 text-xs tabular-nums",
        flat ? "text-muted-foreground" : delta > 0 ? "text-success" : "text-destructive",
        className,
      )}
    >
      <Icon className="size-3.5 shrink-0" aria-hidden />
      {compact ? <span className="sr-only">{text}</span> : text}
    </span>
  );
}

/**
 * A rate on a 0–100 track: one hue for the fill, the track a lighter step of the
 * same surface. The number sits beside it in ink — text never wears the bar's colour.
 */
export function RateMeter({
  value,
  className,
  label,
}: {
  value: number | null | undefined;
  className?: string;
  /** Accessible name, e.g. "Grade 9 · A attendance". */
  label?: string;
}) {
  return (
    <div className={cn("flex min-w-0 items-center gap-2", className)}>
      <span
        className="h-2 min-w-12 flex-1 rounded-e-[4px] bg-muted"
        role="img"
        aria-label={label ? `${label}: ${formatPct(value)}` : formatPct(value)}
      >
        {value != null ? (
          <span
            className="block h-full rounded-e-[4px] bg-chart-1"
            style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
          />
        ) : null}
      </span>
      <span className="w-14 shrink-0 text-end text-sm font-medium tabular-nums">
        {formatPct(value)}
      </span>
    </div>
  );
}

/** Today in the browser's timezone, as the `YYYY-MM-DD` the API expects. */
export function todayIso(): string {
  const now = new Date();
  return toIso(now);
}

export function toIso(date: Date): string {
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 10);
}

/** `YYYY-MM-DD` plus `days` (may be negative), in calendar terms. */
export function shiftIso(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00`);
  date.setDate(date.getDate() + days);
  return toIso(date);
}

/** A neutral-quote CSV cell. Cells that would start a spreadsheet formula are
 *  prefixed with an apostrophe — a class teacher's name is user input. */
export function csvCell(value: string | number | null | undefined): string {
  if (value == null) return "";
  let text = String(value);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** Hand a CSV to the browser as a download. */
export function downloadCsv(filename: string, rows: (string | number | null | undefined)[][]) {
  const body = rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
  // A BOM, so Excel opens UTF-8 (Urdu names) as UTF-8 rather than mojibake.
  const blob = new Blob([`﻿${body}\r\n`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
