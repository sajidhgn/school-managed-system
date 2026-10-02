"use client";

import { useState, type ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { useTranslations } from "@/components/providers/i18n-provider";
import type {
  AttendanceDay,
  AttendancePulse,
  DashboardAnalytics,
  ExamPulse,
  FeePulse,
  StatusMix,
  StudentPulse,
} from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * The dashboard's analytics board.
 *
 * Every chart is hand-drawn SVG or flex boxes: the shapes are simple (bars, a ring,
 * a calendar), and a charting library would be the heaviest dependency on the
 * lightest screen. Colour follows the job it does:
 *
 *   magnitude   one hue (`primary`), light to dark — the attendance calendar
 *   identity    `chart-1` / `chart-2` in fixed order — the gender split
 *   state       success / warning / destructive — register statuses and money owed,
 *               always beside a text label so no reading depends on hue alone
 *
 * A section the caller may not read arrives as null and is simply not drawn.
 */
export function AnalyticsBoard({ data }: { data: DashboardAnalytics }) {
  const { students, attendance, fees, exams } = data;
  if (!students && !attendance && !fees && !exams) return null;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        {attendance ? <PulseCard attendance={attendance} /> : null}
        <div className={cn("grid gap-4 sm:grid-cols-3", !attendance && "lg:col-span-2")}>
          {students ? <StudentsTile students={students} /> : null}
          {attendance ? <AttendanceTile attendance={attendance} /> : null}
          {fees ? <CollectionTile fees={fees} /> : null}
        </div>
      </div>

      {attendance || fees ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {attendance ? <RhythmCard days={attendance.days} /> : null}
          {fees ? <CashflowCard fees={fees} /> : null}
        </div>
      ) : null}

      {students || exams ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {students ? <ClassesCard students={students} /> : null}
          {exams ? <ExamCard exams={exams} /> : null}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared pieces
// ---------------------------------------------------------------------------

function Panel({
  title,
  hint,
  children,
  className,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("relative rounded-xl border border-border bg-card p-5", className)}>
      <h2 className="text-sm font-medium">{title}</h2>
      {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
      <div className="mt-4">{children}</div>
    </section>
  );
}

type Tip = { x: number; y: number; content: ReactNode } | null;

/** Positions a tooltip above the hovered mark, relative to the nearest Panel. */
function useTip() {
  const [tip, setTip] = useState<Tip>(null);
  const show = (event: React.MouseEvent<Element> | React.FocusEvent<Element>, content: ReactNode) => {
    const target = event.currentTarget.getBoundingClientRect();
    const host = (event.currentTarget as Element).closest("section")?.getBoundingClientRect();
    if (!host) return;
    setTip({ x: target.left - host.left + target.width / 2, y: target.top - host.top, content });
  };
  const node = tip ? (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-md"
      style={{ left: tip.x, top: tip.y - 6 }}
    >
      {tip.content}
    </div>
  ) : null;
  return { show, hide: () => setTip(null), node };
}

function pct(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

function money(value: number, compact = false): string {
  return new Intl.NumberFormat("en-PK", {
    style: "currency",
    currency: "PKR",
    maximumFractionDigits: 0,
    ...(compact ? { notation: "compact" as const, maximumFractionDigits: 1 } : {}),
  }).format(value);
}

function fill(template: string, values: Record<string, string | number>): string {
  return Object.entries(values).reduce((s, [k, v]) => s.replace(`{${k}}`, String(v)), template);
}

// ---------------------------------------------------------------------------
// Pulse: two concentric rings — how many children are in, and how many
// registers say so.
// ---------------------------------------------------------------------------

function PulseCard({ attendance }: { attendance: AttendancePulse }) {
  const { t } = useTranslations();
  const { today } = attendance;
  const registers = today.sections_total > 0 ? today.sections_submitted / today.sections_total : 0;

  return (
    <Panel title={t.dashboard.pulse} className="flex flex-col">
      <div className="flex items-center gap-5">
        <svg viewBox="0 0 120 120" className="size-32 shrink-0 -rotate-90" aria-hidden>
          <Ring r={52} width={10} value={today.rate ?? 0} className="stroke-chart-1" />
          <Ring r={36} width={8} value={registers} className="stroke-chart-2" />
        </svg>
        <div className="min-w-0 space-y-3">
          <div>
            <p className="text-3xl font-semibold tabular-nums">
              {today.rate == null ? "—" : pct(today.rate)}
            </p>
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="size-2 rounded-full bg-chart-1" aria-hidden />
              {t.dashboard.attendanceToday}
            </p>
          </div>
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="size-2 rounded-full bg-chart-2" aria-hidden />
            {today.sections_submitted > 0
              ? fill(t.dashboard.registersIn, {
                  done: today.sections_submitted,
                  total: today.sections_total,
                })
              : t.dashboard.noRegisters}
          </p>
        </div>
      </div>
      <div className="mt-auto pt-5">
        <MixBar mix={today.mix} label={t.dashboard.todayMix} />
      </div>
    </Panel>
  );
}

function Ring({
  r,
  width,
  value,
  className,
}: {
  r: number;
  width: number;
  value: number;
  className: string;
}) {
  const circumference = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(1, value));
  return (
    <>
      <circle cx={60} cy={60} r={r} fill="none" strokeWidth={width} className="stroke-muted" />
      <circle
        cx={60}
        cy={60}
        r={r}
        fill="none"
        strokeWidth={width}
        strokeLinecap="round"
        strokeDasharray={`${circumference * clamped} ${circumference}`}
        className={cn(className, "transition-[stroke-dasharray] duration-700 ease-out")}
      />
    </>
  );
}

const MIX_ORDER = [
  { key: "present", label: "present", color: "bg-success" },
  { key: "late", label: "late", color: "bg-warning" },
  { key: "half_day", label: "halfDay", color: "bg-warning/50" },
  { key: "absent", label: "absent", color: "bg-destructive" },
  { key: "excused", label: "excused", color: "bg-muted-foreground/40" },
] as const;

function MixBar({ mix, label }: { mix: StatusMix; label: string }) {
  const { t } = useTranslations();
  const total = MIX_ORDER.reduce((sum, m) => sum + (mix[m.key] ?? 0), 0);
  if (total === 0) return null;
  const parts = MIX_ORDER.filter((m) => (mix[m.key] ?? 0) > 0);

  return (
    <div>
      <p className="mb-2 text-xs text-muted-foreground">{label}</p>
      <div className="flex h-2.5 gap-0.5 overflow-hidden rounded-full" role="img" aria-label={label}>
        {parts.map((m) => (
          <div
            key={m.key}
            className={cn("h-full first:rounded-s-full last:rounded-e-full", m.color)}
            style={{ width: `${((mix[m.key] ?? 0) / total) * 100}%` }}
          />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
        {parts.map((m) => (
          <li key={m.key} className="flex items-center gap-1.5">
            <span className={cn("size-2 rounded-full", m.color)} aria-hidden />
            <span className="text-muted-foreground">{t.dashboard[m.label]}</span>
            <span className="font-medium tabular-nums">{mix[m.key]}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// KPI tiles
// ---------------------------------------------------------------------------

function Tile({ label, value, children }: { label: string; value: string; children?: ReactNode }) {
  return (
    <section className="relative flex flex-col rounded-xl border border-border bg-card p-5">
      <h2 className="text-sm text-muted-foreground">{label}</h2>
      <p className="mt-2 text-3xl font-semibold tabular-nums">{value}</p>
      <div className="mt-auto pt-3 text-xs text-muted-foreground">{children}</div>
    </section>
  );
}

function StudentsTile({ students }: { students: StudentPulse }) {
  const { t } = useTranslations();
  return (
    <Tile label={t.dashboard.activeStudents} value={students.active.toLocaleString()}>
      <p className={cn(students.joined_last_30_days > 0 && "text-success")}>
        {fill(t.dashboard.joinedRecently, { count: students.joined_last_30_days })}
      </p>
      {students.pending > 0 ? (
        <p>{fill(t.dashboard.pendingAdmissions, { count: students.pending })}</p>
      ) : null}
    </Tile>
  );
}

function AttendanceTile({ attendance }: { attendance: AttendancePulse }) {
  const { t } = useTranslations();
  const { rate_30d: now, rate_prev_30d: before } = attendance;
  const delta = now != null && before != null ? now - before : null;
  const Icon = delta == null || Math.abs(delta) < 0.0005 ? Minus : delta > 0 ? ArrowUpRight : ArrowDownRight;

  return (
    <Tile label={t.dashboard.attendance30d} value={now == null ? "—" : pct(now, 1)}>
      <Sparkline days={attendance.days} />
      <p
        className={cn(
          "mt-2 flex items-center gap-1",
          delta != null && delta > 0.0005 && "text-success",
          delta != null && delta < -0.0005 && "text-destructive",
        )}
      >
        <Icon className="size-3.5" aria-hidden />
        {delta == null
          ? t.dashboard.noComparison
          : fill(t.dashboard.vsPrevious, {
              delta: `${delta >= 0 ? "+" : "−"}${Math.abs(delta * 100).toFixed(1)} pts`,
            })}
      </p>
    </Tile>
  );
}

/** Marked days only: a gap for an unmarked day would draw a weekend as a cliff. */
function Sparkline({ days }: { days: AttendanceDay[] }) {
  const points = days.filter((d) => d.rate != null) as (AttendanceDay & { rate: number })[];
  if (points.length < 2) return null;
  const lo = Math.min(...points.map((p) => p.rate));
  const hi = Math.max(...points.map((p) => p.rate));
  const span = Math.max(hi - lo, 0.05);
  const path = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * 100;
      const y = 22 - ((p.rate - lo) / span) * 20;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  return (
    <svg viewBox="0 0 100 24" preserveAspectRatio="none" className="h-6 w-full" aria-hidden>
      <path
        d={path}
        fill="none"
        strokeWidth={2}
        vectorEffect="non-scaling-stroke"
        strokeLinejoin="round"
        strokeLinecap="round"
        className="stroke-chart-1"
      />
    </svg>
  );
}

function CollectionTile({ fees }: { fees: FeePulse }) {
  const { t } = useTranslations();
  const billed = Number(fees.billed);
  const collected = Number(fees.collected);
  const overdue = Number(fees.overdue);
  const pending = Math.max(0, billed - collected - overdue);

  return (
    <Tile
      label={t.dashboard.collectionRate}
      value={fees.collection_rate == null ? "—" : pct(fees.collection_rate)}
    >
      {billed > 0 ? (
        <>
          <div className="flex h-2 gap-0.5 overflow-hidden rounded-full" role="img" aria-label={t.dashboard.ledger}>
            {[
              [collected, "bg-success"],
              [pending, "bg-muted-foreground/30"],
              [overdue, "bg-destructive"],
            ]
              .filter(([v]) => (v as number) > 0)
              .map(([v, color]) => (
                <div
                  key={color as string}
                  className={cn("h-full first:rounded-s-full last:rounded-e-full", color as string)}
                  style={{ width: `${((v as number) / billed) * 100}%` }}
                />
              ))}
          </div>
          <p className="mt-2">
            {fill(t.dashboard.collectedOfBilled, {
              collected: money(collected, true),
              billed: money(billed, true),
            })}
          </p>
          {overdue > 0 ? (
            <p className="flex items-center gap-1.5">
              <span className="size-2 rounded-full bg-destructive" aria-hidden />
              {t.dashboard.overdue} <span className="font-medium text-foreground">{money(overdue, true)}</span>
            </p>
          ) : null}
        </>
      ) : (
        <p>{t.dashboard.nothingBilled}</p>
      )}
    </Tile>
  );
}

// ---------------------------------------------------------------------------
// Attendance rhythm: a five-week calendar, one hue light to dark.
// ---------------------------------------------------------------------------

/** Five steps over the range schools actually live in. A linear 0–100% scale
 *  would paint every ordinary day the same dark square. */
const RHYTHM_STEPS = [0.7, 0.8, 0.88, 0.94] as const;
const RHYTHM_FILLS = [
  "color-mix(in oklch, var(--primary) 18%, var(--card))",
  "color-mix(in oklch, var(--primary) 36%, var(--card))",
  "color-mix(in oklch, var(--primary) 56%, var(--card))",
  "color-mix(in oklch, var(--primary) 78%, var(--card))",
  "var(--primary)",
];

function rhythmFill(rate: number): string {
  const step = RHYTHM_STEPS.findIndex((edge) => rate < edge);
  return RHYTHM_FILLS[step === -1 ? RHYTHM_FILLS.length - 1 : step]!;
}

function RhythmCard({ days }: { days: AttendanceDay[] }) {
  const { t, locale } = useTranslations();
  const { show, hide, node } = useTip();

  // Monday-first rows. Leading blanks put the first day under its weekday.
  const first = new Date(`${days[0]!.day}T00:00:00`);
  const lead = (first.getDay() + 6) % 7;
  const cells: (AttendanceDay | null)[] = [...Array<null>(lead).fill(null), ...days];
  while (cells.length % 7 !== 0) cells.push(null);

  const weekday = new Intl.DateTimeFormat(locale, { weekday: "narrow" });
  const longDate = new Intl.DateTimeFormat(locale, { weekday: "short", day: "numeric", month: "short" });
  const headers = Array.from({ length: 7 }, (_, i) => weekday.format(new Date(2024, 0, 1 + i)));
  const today = days[days.length - 1]!.day;

  return (
    <Panel title={t.dashboard.rhythm} hint={t.dashboard.rhythmHint}>
      <div className="grid grid-cols-7 gap-1.5" onMouseLeave={hide}>
        {headers.map((h, i) => (
          <div key={`h${i}`} className="pb-1 text-center text-[11px] text-muted-foreground">
            {h}
          </div>
        ))}
        {cells.map((cell, i) => {
          if (!cell) return <div key={`b${i}`} className="aspect-square" />;
          const label = `${longDate.format(new Date(`${cell.day}T00:00:00`))} · ${
            cell.rate == null ? t.dashboard.notMarked : pct(cell.rate, 1)
          }`;
          return (
            <button
              key={cell.day}
              type="button"
              aria-label={label}
              onMouseEnter={(e) => show(e, label)}
              onFocus={(e) => show(e, label)}
              onBlur={hide}
              className={cn(
                "aspect-square rounded-md outline-none transition-transform hover:scale-110 focus-visible:ring-2 focus-visible:ring-ring",
                cell.rate == null && "border border-dashed border-border",
                cell.day === today && "ring-2 ring-foreground/70 ring-offset-2 ring-offset-card",
              )}
              style={cell.rate == null ? undefined : { background: rhythmFill(cell.rate) }}
            />
          );
        })}
      </div>
      <div className="mt-4 flex items-center justify-end gap-1.5 text-[11px] text-muted-foreground">
        <span>{t.dashboard.less}</span>
        {RHYTHM_FILLS.map((f) => (
          <span key={f} className="size-3 rounded-sm" style={{ background: f }} aria-hidden />
        ))}
        <span>{t.dashboard.more}</span>
      </div>
      {node}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Fee receipts by month
// ---------------------------------------------------------------------------

function CashflowCard({ fees }: { fees: FeePulse }) {
  const { t, locale } = useTranslations();
  const { show, hide, node } = useTip();
  const values = fees.months.map((m) => Number(m.collected));
  const max = Math.max(...values, 0);
  const monthName = new Intl.DateTimeFormat(locale, { month: "short" });
  const monthLong = new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" });
  const label = (m: string) => new Date(`${m}-01T00:00:00`);
  const peak = values.indexOf(max);

  return (
    <Panel title={t.dashboard.cashflow} hint={t.dashboard.cashflowHint}>
      {max === 0 ? (
        <Empty />
      ) : (
        <>
          <div className="flex h-44 items-end gap-1.5 border-b border-border" onMouseLeave={hide}>
            {fees.months.map((m, i) => {
              const text = `${monthLong.format(label(m.month))} · ${money(values[i]!)}`;
              return (
                <button
                  key={m.month}
                  type="button"
                  aria-label={text}
                  onMouseEnter={(e) => show(e, text)}
                  onFocus={(e) => show(e, text)}
                  onBlur={hide}
                  className="group relative flex h-full flex-1 items-end outline-none"
                >
                  {i === peak ? (
                    <span className="absolute inset-x-0 -translate-y-5 text-center text-[11px] font-medium tabular-nums">
                      {money(max, true)}
                    </span>
                  ) : null}
                  <span
                    className={cn(
                      "w-full rounded-t-[4px] bg-chart-1 transition-opacity group-hover:opacity-80 group-focus-visible:ring-2 group-focus-visible:ring-ring",
                      i !== fees.months.length - 1 && "opacity-70",
                    )}
                    style={{ height: `${Math.max((values[i]! / max) * 100, values[i]! > 0 ? 2 : 0)}%` }}
                  />
                </button>
              );
            })}
          </div>
          <div className="mt-1.5 flex gap-1.5">
            {fees.months.map((m, i) => (
              <span
                key={m.month}
                className={cn(
                  "flex-1 text-center text-[10px] text-muted-foreground",
                  i % 2 === 1 && i !== fees.months.length - 1 && "max-sm:invisible",
                )}
              >
                {monthName.format(label(m.month))}
              </span>
            ))}
          </div>
        </>
      )}
      {node}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Students: class headcounts and the gender split
// ---------------------------------------------------------------------------

function ClassesCard({ students }: { students: StudentPulse }) {
  const { t } = useTranslations();
  const max = Math.max(...students.by_class.map((c) => c.count), 0);
  const total = students.gender.reduce((s, g) => s + g.count, 0);

  return (
    <Panel title={t.dashboard.classes}>
      {students.by_class.length === 0 ? (
        <Empty />
      ) : (
        <ul className="space-y-2">
          {students.by_class.map((c) => (
            <li key={`${c.level}-${c.class_name}`} className="grid grid-cols-[6.5rem_1fr_2.5rem] items-center gap-3 text-sm">
              <span className="truncate text-muted-foreground">{c.class_name}</span>
              <span className="h-2.5 rounded-e-[4px] bg-muted">
                <span
                  className="block h-full rounded-e-[4px] bg-chart-1"
                  style={{ width: `${max ? (c.count / max) * 100 : 0}%` }}
                />
              </span>
              <span className="text-end font-medium tabular-nums">{c.count}</span>
            </li>
          ))}
        </ul>
      )}
      {students.unplaced > 0 ? (
        <p className="mt-3 text-xs text-warning-foreground dark:text-warning">
          {fill(t.dashboard.unplaced, { count: students.unplaced })}
        </p>
      ) : null}

      {total > 0 ? (
        <div className="mt-6">
          <p className="mb-2 text-xs text-muted-foreground">{t.dashboard.gender}</p>
          <GenderSplit gender={students.gender} total={total} />
        </div>
      ) : null}
    </Panel>
  );
}

// Fixed order, so a school with no boys does not repaint its girls.
const GENDER_COLORS: Record<string, string> = {
  male: "bg-chart-1",
  female: "bg-chart-2",
  other: "bg-muted-foreground/50",
  unspecified: "bg-muted-foreground/25",
};
const GENDER_ORDER = ["male", "female", "other", "unspecified"] as const;

function GenderSplit({ gender, total }: { gender: StudentPulse["gender"]; total: number }) {
  const { t } = useTranslations();
  const counts = Object.fromEntries(gender.map((g) => [g.gender, g.count]));
  const parts = GENDER_ORDER.filter((g) => (counts[g] ?? 0) > 0);

  return (
    <>
      <div className="flex h-3 gap-0.5 overflow-hidden rounded-full" role="img" aria-label={t.dashboard.gender}>
        {parts.map((g) => (
          <div
            key={g}
            className={cn("h-full first:rounded-s-full last:rounded-e-full", GENDER_COLORS[g])}
            style={{ width: `${(counts[g]! / total) * 100}%` }}
          />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {parts.map((g) => (
          <li key={g} className="flex items-center gap-1.5">
            <span className={cn("size-2 rounded-full", GENDER_COLORS[g])} aria-hidden />
            <span className="text-muted-foreground">{t.dashboard[g]}</span>
            <span className="font-medium tabular-nums">{counts[g]}</span>
            <span className="text-muted-foreground">({pct(counts[g]! / total)})</span>
          </li>
        ))}
      </ul>
    </>
  );
}

// ---------------------------------------------------------------------------
// Exams: subjects ranked by average score
// ---------------------------------------------------------------------------

function ExamCard({ exams }: { exams: ExamPulse }) {
  const { t } = useTranslations();
  const { show, hide, node } = useTip();

  return (
    <Panel title={t.dashboard.examTitle} hint={fill(t.dashboard.examHint, { exam: exams.exam_name })}>
      <ul className="space-y-3" onMouseLeave={hide}>
        {exams.subjects.map((s) => {
          const text = [
            `${s.subject} · ${s.average_pct.toFixed(1)}%`,
            s.pass_rate == null ? null : `${pct(s.pass_rate)} ${t.dashboard.passRate}`,
            fill(t.dashboard.sat, { count: s.sat }),
          ]
            .filter(Boolean)
            .join(" · ");
          return (
            <li key={s.subject}>
              <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
                <span className="truncate">{s.subject}</span>
                <span className="shrink-0 tabular-nums">
                  <span className="font-medium">{s.average_pct.toFixed(0)}%</span>
                  {s.pass_rate != null ? (
                    <span className="ms-2 text-xs text-muted-foreground">
                      {pct(s.pass_rate)} {t.dashboard.passRate}
                    </span>
                  ) : null}
                </span>
              </div>
              <button
                type="button"
                aria-label={text}
                onMouseEnter={(e) => show(e, text)}
                onFocus={(e) => show(e, text)}
                onBlur={hide}
                className="block h-2.5 w-full rounded-e-[4px] bg-muted outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span
                  className="block h-full rounded-e-[4px] bg-chart-1"
                  style={{ width: `${Math.min(100, s.average_pct)}%` }}
                />
              </button>
            </li>
          );
        })}
      </ul>
      {node}
    </Panel>
  );
}

function Empty() {
  const { t } = useTranslations();
  return (
    <p className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
      {t.dashboard.emptyChart}
    </p>
  );
}
