"use client";

import * as React from "react";
import Link from "next/link";
import { Download, FileText, Receipt, Settings2, Wallet } from "lucide-react";

import { ChallanDesignDialog, type ChallanSchool } from "./challan-design-dialog";
import { GenerateChallansDialog } from "./generate-challans-dialog";
import { EmptyState, ErrorState, TableCardSkeleton } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { VoucherStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useFeeSummary, useVouchers } from "@/hooks/use-fees";
import { feesApi } from "@/lib/api/resources/fees";
import { currentAcademicYear } from "@/lib/academic-year";
import { label } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { feesMessages } from "@/lib/i18n/modules/fees";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { useLabels } from "@/lib/i18n/use-labels";
import { formatDate } from "@/lib/utils";

/**
 * Money in, money owed, for one campus and one period.
 *
 * =============================================================================
 * THE PERIOD IS THE PAGE'S SUBJECT, NOT A FILTER ON IT
 * =============================================================================
 *   Every figure here — billed, collected, outstanding — is meaningless without an
 *   academic year, and the backend requires one. So the period controls sit at the
 *   TOP, above the totals they produce, rather than beside the table as a filter.
 *   Read top to bottom the page says: for this year and this month, here is what was
 *   billed and what is still owed, and here are the challans behind those numbers.
 *
 *   Status, by contrast, IS a filter: it narrows the register without changing what
 *   the totals mean, so it sits with the table.
 */

const PAGE_SIZE = 20;

export function FeesView({
  canIssue,
  canCollect,
  canManage,
  canDesignChallan,
  school,
}: {
  canIssue: boolean;
  canCollect: boolean;
  canManage: boolean;
  canDesignChallan: boolean;
  school: ChallanSchool | null;
}) {
  const m = useCatalog(feesMessages).register;
  const L = useLabels();
  const [academicYear, setAcademicYear] = React.useState(currentAcademicYear);
  const [period, setPeriod] = React.useState("");
  const [status, setStatus] = React.useState<string>("all");
  const [page, setPage] = React.useState(1);
  const [generating, setGenerating] = React.useState(false);
  const [designing, setDesigning] = React.useState(false);

  const trimmedPeriod = period.trim();

  const summary = useFeeSummary(academicYear, trimmedPeriod || undefined);
  const vouchers = useVouchers({
    page,
    size: PAGE_SIZE,
    academic_year: academicYear,
    ...(trimmedPeriod ? { period_label: trimmedPeriod } : {}),
    ...(status !== "all" ? { status } : {}),
  });

  // Any change to what is being asked about starts the register at the top again;
  // staying on page 7 of a different question is disorienting.
  function reframe(fn: () => void) {
    fn();
    setPage(1);
  }

  const currency = summary.data?.currency ?? "PKR";
  const money = React.useMemo(
    () =>
      new Intl.NumberFormat("en-PK", {
        style: "currency",
        currency,
        maximumFractionDigits: 0,
      }),
    [currency],
  );

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title={m.title}
        description={m.description}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {canManage ? (
              <Button variant="outline" asChild>
                <Link href="/fees/setup">
                  <Settings2 className="size-4" aria-hidden />
                  {m.headsAndStructures}
                </Link>
              </Button>
            ) : null}
            {canDesignChallan && school ? (
              <Button variant="outline" onClick={() => setDesigning(true)}>
                <FileText className="size-4" aria-hidden />
                {m.challanDesign}
              </Button>
            ) : null}
            {canIssue ? (
              <Button onClick={() => setGenerating(true)}>
                <Receipt className="size-4" aria-hidden />
                {m.generateChallans}
              </Button>
            ) : null}
          </div>
        }
      />

      {/* --- What the figures below are about ------------------------------ */}
      <div className="mb-6 flex flex-wrap items-end gap-3">
        <label className="grid gap-1.5 text-sm">
          <span className="font-medium">{m.academicYear}</span>
          <Input
            value={academicYear}
            onChange={(event) => reframe(() => setAcademicYear(event.target.value))}
            placeholder="2026-2027"
            className="w-40"
            inputMode="numeric"
          />
        </label>
        {/* Matches on the challan's description — the same string the generate
            dialog asks for. Named the same here as there, because a filter whose
            label disagrees with the field it filters is a filter nobody trusts. */}
        <label className="grid gap-1.5 text-sm">
          <span className="font-medium">{m.descriptionLabel}</span>
          <Input
            value={period}
            onChange={(event) => reframe(() => setPeriod(event.target.value))}
            placeholder={m.descriptionPlaceholder}
            className="w-52"
          />
        </label>
      </div>

      {/* --- Totals -------------------------------------------------------- */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {/* Stationery rides on the Billed tile's hint rather than taking a fifth
            tile of its own, because it is a PART of billed, not a figure beside it.
            A tile would invite the reader to add it to the other four. Shown only
            when something was actually sold — otherwise it reads as a zero worth
            worrying about. */}
        <Figure
          label={m.billed}
          value={summary.data ? money.format(Number(summary.data.billed)) : "—"}
          hint={
            summary.data
              ? [
                  fill(summary.data.voucher_count === 1 ? m.challansOne : m.challansMany, {
                    count: summary.data.voucher_count,
                  }),
                  Number(summary.data.stationery_billed) > 0
                    ? fill(m.stationeryBilled, {
                        amount: money.format(Number(summary.data.stationery_billed)),
                      })
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")
              : undefined
          }
          loading={summary.isPending}
        />
        <Figure
          label={m.collected}
          value={summary.data ? money.format(Number(summary.data.collected)) : "—"}
          tone="success"
          loading={summary.isPending}
        />
        <Figure
          label={m.outstanding}
          value={summary.data ? money.format(Number(summary.data.outstanding)) : "—"}
          tone={summary.data && Number(summary.data.outstanding) > 0 ? "warning" : undefined}
          loading={summary.isPending}
        />
        <Figure
          label={m.overdue}
          value={summary.data ? money.format(Number(summary.data.overdue)) : "—"}
          hint={m.overdueHint}
          tone={summary.data && Number(summary.data.overdue) > 0 ? "destructive" : undefined}
          loading={summary.isPending}
        />
      </div>

      {/* --- The register -------------------------------------------------- */}
      <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">{m.challans}</h2>
        <div className="flex flex-wrap items-center gap-2">
          {/* Exports what the register shows — same year, description and status —
              across every page, not only the one in view. */}
          <Button variant="outline" asChild>
            <a
              href={feesApi.vouchers.exportUrl({
                academic_year: academicYear.trim(),
                period_label: trimmedPeriod,
                status: status !== "all" ? status : undefined,
              })}
              download
            >
              <Download className="size-4" aria-hidden />
              {m.exportCsv}
            </a>
          </Button>
          <Select value={status} onValueChange={(value) => reframe(() => setStatus(value))}>
            <SelectTrigger className="w-44">
              <SelectValue placeholder={m.allStatuses} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{m.allStatuses}</SelectItem>
              {Object.keys(L.voucherStatus).map((value) => (
                <SelectItem key={value} value={value}>
                  {label(L.voucherStatus, value)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <Card className="mt-3 overflow-hidden p-0">
        {vouchers.isPending ? (
          <TableCardSkeleton columns={6} />
        ) : vouchers.isError ? (
          <ErrorState error={vouchers.error} onRetry={() => void vouchers.refetch()} />
        ) : vouchers.data.items.length === 0 ? (
          <EmptyState
            icon={Wallet}
            title={m.emptyTitle}
            description={canIssue ? m.emptyCanIssue : m.emptyReadOnly}
            action={
              canIssue ? (
                <Button onClick={() => setGenerating(true)}>{m.generateChallans}</Button>
              ) : undefined
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{m.colStudent}</TableHead>
                  <TableHead>{m.colChallan}</TableHead>
                  <TableHead>{m.colDue}</TableHead>
                  <TableHead className="text-end">{m.colTotal}</TableHead>
                  <TableHead className="text-end">{m.colOutstanding}</TableHead>
                  <TableHead>{m.colStatus}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {vouchers.data.items.map((voucher) => (
                  <TableRow key={voucher.id} className="relative hover:bg-accent/40">
                    <TableCell>
                      <Link
                        href={`/fees/${voucher.id}`}
                        className="font-medium outline-none after:absolute after:inset-0 focus-visible:underline"
                      >
                        {voucher.student_name}
                      </Link>
                      <div className="text-xs text-muted-foreground">
                        {voucher.admission_number}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm">
                      <div className="font-mono text-xs">{voucher.voucher_number}</div>
                      <div className="text-xs text-muted-foreground">{voucher.period_label}</div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                      {formatDate(voucher.due_date)}
                    </TableCell>
                    <TableCell className="text-end tabular-nums">
                      {money.format(Number(voucher.total))}
                    </TableCell>
                    <TableCell className="text-end tabular-nums">
                      {Number(voucher.outstanding) > 0 ? (
                        <span className="font-medium">
                          {money.format(Number(voucher.outstanding))}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <VoucherStatusBadge status={voucher.status} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>

      {vouchers.data ? (
        <div className="mt-4">
          <Pagination
            meta={vouchers.data.meta}
            onPageChange={setPage}
            disabled={vouchers.isFetching}
          />
        </div>
      ) : null}

      {canIssue ? (
        <GenerateChallansDialog
          open={generating}
          onOpenChange={setGenerating}
          academicYear={academicYear}
          canCollect={canCollect}
        />
      ) : null}

      {canDesignChallan ? (
        <ChallanDesignDialog open={designing} onOpenChange={setDesigning} school={school} />
      ) : null}
    </div>
  );
}

/**
 * One headline number.
 *
 * Tone is applied to the VALUE, not the card: a coloured card competes with the
 * status pills in the table below it, and there are four of these side by side.
 */
function Figure({
  label: labelText,
  value,
  hint,
  tone,
  loading,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "success" | "warning" | "destructive";
  loading?: boolean;
}) {
  const toneClass =
    tone === "success"
      ? "text-success"
      : tone === "warning"
        ? "text-warning-foreground dark:text-warning"
        : tone === "destructive"
          ? "text-destructive"
          : "";

  return (
    <Card className="p-4">
      <p className="text-xs text-muted-foreground">{labelText}</p>
      <p
        className={`mt-1 text-2xl font-semibold tabular-nums ${toneClass} ${
          loading ? "animate-pulse text-muted-foreground" : ""
        }`}
      >
        {value}
      </p>
      {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
    </Card>
  );
}
