import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Download } from "lucide-react";

import {
  AttendanceCalendarView,
  type AttendanceCalendarLabels,
} from "@/components/attendance/student-attendance-panel";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { serverGet, serverGetOrNull } from "@/lib/api/server";
import type {
  GuardianChildRead,
  PortalExamResult,
  PortalFeeStatement,
  StudentAttendanceCalendar,
} from "@/lib/api/types";
import { requireGuardian } from "@/lib/auth/session";
import type { Messages } from "@/lib/i18n/messages";
import { getLocale, getTranslations } from "@/lib/i18n/server";
import { cn, formatDate } from "@/lib/utils";

import { ParentHeader } from "../../parent-header";

export const metadata: Metadata = { title: "Child" };
export const dynamic = "force-dynamic";

/**
 * One child, for their parent: attendance, fees and published results.
 *
 * Every read is a portal endpoint that resolves the child through the parent's link
 * first, so an id this parent may not view is a 404 here as it is there. The
 * numbers come from the same services the office uses -- this page only lays them
 * out for a phone.
 */
export default async function ParentChildPage({
  params,
}: {
  params: Promise<{ studentId: string }>;
}) {
  const { studentId } = await params;
  const guardian = await requireGuardian();
  const base = `/portal/children/${encodeURIComponent(studentId)}`;

  const child = await serverGetOrNull<GuardianChildRead>(base, "guardian");
  if (!child) notFound();

  const [t, locale, attendance, fees, results] = await Promise.all([
    getTranslations(),
    getLocale(),
    serverGet<StudentAttendanceCalendar | null>(`${base}/attendance`, null, "guardian"),
    serverGet<PortalFeeStatement | null>(`${base}/fees`, null, "guardian"),
    serverGet<PortalExamResult[]>(`${base}/results`, [], "guardian"),
  ]);
  const p = t.parent;

  return (
    <div className="min-h-svh bg-muted/40">
      <ParentHeader organizationName={guardian.organization_name} />

      <main id="main" className="mx-auto w-full max-w-2xl space-y-5 px-4 py-6">
        <div>
          <Link
            href="/parent"
            className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4 rtl:rotate-180" aria-hidden />
            {p.backToChildren}
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">{child.full_name}</h1>
          <p className="text-sm text-muted-foreground">
            {child.school_name} · {p.admissionNo}{" "}
            <bdi dir="ltr" className="tabular-nums">
              {child.admission_number}
            </bdi>
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>{p.attendanceTitle}</CardTitle>
          </CardHeader>
          <CardContent>
            {attendance && attendance.months.length > 0 ? (
              <AttendanceCalendarView
                calendar={attendance}
                labels={calendarLabels(p, locale)}
              />
            ) : (
              <p className="text-sm text-muted-foreground">{p.attendanceEmpty}</p>
            )}
          </CardContent>
        </Card>

        <FeesCard fees={fees} studentId={child.student_id} p={p} locale={locale} />

        <ResultsCard results={results} p={p} />
      </main>
    </div>
  );
}

type ParentMessages = Messages["parent"];

function calendarLabels(p: ParentMessages, locale: string): AttendanceCalendarLabels {
  return {
    locale: locale === "ur" ? "ur-PK" : "en-PK",
    yearSoFar: p.calYearSoFar,
    noRegisters: p.calNoRegisters,
    breakdown: p.calBreakdown,
    previousMonth: p.calPrevious,
    nextMonth: p.calNext,
    gridLabel: p.attendanceTitle,
    registerOpen: p.calRegisterOpen,
    registerOpenDay: p.calRegisterOpenDay,
    upcoming: p.calUpcoming,
    noRegister: p.calNoRegister,
    weekdays: p.calWeekdays.split(" "),
    status: {
      present: p.statusPresent,
      late: p.statusLate,
      half_day: p.statusHalfDay,
      absent: p.statusAbsent,
      excused: p.statusExcused,
    },
  };
}

function money(amount: string | number, currency: string): string {
  // Latin digits in both languages: the challan the bank reads prints them that way.
  return new Intl.NumberFormat("en-PK", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(Number(amount));
}

const VOUCHER_BADGE = {
  issued: "neutral",
  partly_paid: "warning",
  paid: "success",
  overdue: "destructive",
} as const;

function FeesCard({
  fees,
  studentId,
  p,
  locale,
}: {
  fees: PortalFeeStatement | null;
  studentId: string;
  p: ParentMessages;
  locale: string;
}) {
  // Split rather than replaced, so the date stays one left-to-right run in Urdu.
  const [dueBefore, dueAfter = ""] = p.feesDue.split("{date}");
  const statusLabel: Record<string, string> = {
    issued: p.voucherIssued,
    partly_paid: p.voucherPartlyPaid,
    paid: p.voucherPaid,
    overdue: p.voucherOverdue,
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{p.feesTitle}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {!fees || fees.vouchers.length === 0 ? (
          <p className="text-sm text-muted-foreground">{p.feesNone}</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-border p-3">
                <p className="text-xs text-muted-foreground">{p.feesOutstanding}</p>
                <p className="mt-1 text-xl font-semibold tabular-nums">
                  {money(fees.outstanding_total, fees.currency)}
                </p>
              </div>
              <div className="rounded-lg border border-border p-3">
                <p className="text-xs text-muted-foreground">{p.feesOverdue}</p>
                <p
                  className={cn(
                    "mt-1 text-xl font-semibold tabular-nums",
                    Number(fees.overdue_total) > 0 && "text-destructive",
                  )}
                >
                  {money(fees.overdue_total, fees.currency)}
                </p>
              </div>
            </div>
            <p className="text-sm text-muted-foreground">{p.feesPayHint}</p>

            <ul className="divide-y divide-border rounded-lg border border-border">
              {fees.vouchers.map((voucher) => (
                <li key={voucher.id} className="space-y-2 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="font-medium">{periodName(voucher.period_label, locale)}</p>
                      <p className="text-xs text-muted-foreground">
                        {dueBefore}
                        <bdi dir="ltr" className="whitespace-nowrap">
                          {formatDate(voucher.due_date)}
                        </bdi>
                        {dueAfter} ·{" "}
                        <bdi dir="ltr" className="whitespace-nowrap">
                          {voucher.voucher_number}
                        </bdi>
                      </p>
                    </div>
                    <Badge
                      variant={
                        VOUCHER_BADGE[voucher.status as keyof typeof VOUCHER_BADGE] ?? "neutral"
                      }
                    >
                      {statusLabel[voucher.status] ?? voucher.status}
                    </Badge>
                  </div>
                  <dl className="grid grid-cols-3 gap-2 text-sm">
                    <Amount label={p.feesTotal} value={money(voucher.total, voucher.currency)} />
                    <Amount label={p.feesPaid} value={money(voucher.paid_total, voucher.currency)} />
                    <Amount
                      label={p.feesBalance}
                      value={money(voucher.outstanding, voucher.currency)}
                      strong={Number(voucher.outstanding) > 0}
                    />
                  </dl>
                  {Number(voucher.outstanding) > 0 ? (
                    <a
                      href={`/api/parent/children/${studentId}/challan/${voucher.id}`}
                      className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
                    >
                      <Download className="size-4" aria-hidden />
                      {p.feesDownload}
                    </a>
                  ) : null}
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Amount({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("tabular-nums", strong && "font-semibold")}>{value}</dd>
    </div>
  );
}

/** `2026-08` → `August 2026` (or `اگست 2026`); any other label prints as it is. */
function periodName(label: string, locale: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(label);
  if (!match) return label;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, 1);
  return new Intl.DateTimeFormat(locale === "ur" ? "ur-PK" : "en-GB", {
    month: "long",
    year: "numeric",
  }).format(date);
}

function ResultsCard({ results, p }: { results: PortalExamResult[]; p: ParentMessages }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{p.resultsTitle}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {results.length === 0 ? (
          <p className="text-sm text-muted-foreground">{p.resultsNone}</p>
        ) : (
          results.map((result) => (
            <section key={result.exam_id} className="rounded-lg border border-border">
              <div className="flex items-start justify-between gap-3 border-b border-border p-3">
                <div className="min-w-0">
                  <h3 className="font-medium">{result.exam_name}</h3>
                  <p className="text-xs text-muted-foreground">
                    {result.class_name}
                    {examDates(result) ? (
                      <>
                        {" · "}
                        <bdi dir="ltr" className="whitespace-nowrap">
                          {examDates(result)}
                        </bdi>
                      </>
                    ) : null}
                  </p>
                </div>
                <div className="text-end">
                  <p className="text-xl font-semibold tabular-nums">
                    <bdi dir="ltr">{Number(result.percentage).toFixed(1)}%</bdi>
                  </p>
                  {result.rank !== null && result.class_size !== null ? (
                    <p className="text-xs text-muted-foreground">
                      {p.resultsPosition
                        .replace("{rank}", String(result.rank))
                        .replace("{size}", String(result.class_size))}
                    </p>
                  ) : null}
                </div>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground">
                    <th className="px-3 py-2 text-start font-normal">{p.resultsSubject}</th>
                    <th className="px-3 py-2 text-end font-normal">{p.resultsMarks}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {result.papers.map((paper) => {
                    const obtained = paper.marks_obtained === null ? null : Number(paper.marks_obtained);
                    const failed =
                      obtained !== null && paper.pass_marks !== null && obtained < paper.pass_marks;
                    return (
                      <tr key={paper.subject_name}>
                        <td className="px-3 py-2">{paper.subject_name}</td>
                        <td
                          className={cn(
                            "px-3 py-2 text-end tabular-nums",
                            (failed || paper.is_absent) && "text-destructive",
                          )}
                        >
                          {paper.is_absent ? (
                            p.resultsAbsent
                          ) : !paper.marked ? (
                            <span className="text-muted-foreground">{p.resultsNotMarked}</span>
                          ) : (
                            <bdi dir="ltr">
                              {formatMarks(obtained)} / {paper.max_marks}
                            </bdi>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="border-t border-border font-medium">
                    <td className="px-3 py-2">{p.resultsTotal}</td>
                    <td className="px-3 py-2 text-end tabular-nums">
                      <bdi dir="ltr">
                        {formatMarks(Number(result.total_obtained))} / {result.total_max}
                      </bdi>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </section>
          ))
        )}
      </CardContent>
    </Card>
  );
}

/** `76.00` → `76`, `42.50` → `42.5`: half marks are routine, trailing zeros are noise. */
function formatMarks(value: number | null): string {
  return value === null ? "—" : String(Number(value.toFixed(2)));
}

function examDates(result: PortalExamResult): string | null {
  if (!result.start_date) return null;
  if (!result.end_date || result.end_date === result.start_date) {
    return formatDate(result.start_date);
  }
  return `${formatDate(result.start_date)} – ${formatDate(result.end_date)}`;
}
