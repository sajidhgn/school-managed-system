"use client";

import * as React from "react";
import Link from "next/link";
import {
  Ban,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Printer,
  Receipt,
  Send,
  Trash2,
  Undo2,
  Wallet,
} from "lucide-react";

import { GenerateChallansDialog } from "../../fees/generate-challans-dialog";
import { EmptyState, ErrorState, TableCardSkeleton } from "@/components/data-states";
import { AddChargeForm } from "@/components/fees/add-charge-form";
import { RecordPaymentDialog } from "@/components/fees/record-payment-dialog";
import { StudentFeeArrangement } from "@/components/fees/student-fee-arrangement";
import { ReasonDialog } from "@/components/fees/reason-dialog";
import { VoucherStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useIssueVoucher,
  useRemoveVoucherStationery,
  useReversePayment,
  useVoidVoucher,
  useVoucher,
  useVouchers,
} from "@/hooks/use-fees";
import { feesApi } from "@/lib/api/resources/fees";
import {
  PAYMENT_METHOD_LABELS,
  label,
  unitLabel,
  type FeeVoucherRead,
} from "@/lib/api/types";
import { currentAcademicYear } from "@/lib/academic-year";
import { formatDate } from "@/lib/utils";

// Mirrors `MAX_CHALLAN_VOUCHERS` in the fees router. Stated twice on purpose: the
// server is the guarantee, and this stops an operator ticking a fourteenth box only
// to be told no after they have chosen.
const MAX_COMBINED = 12;

/**
 * Everything this one student owes, has paid, and can be made to pay — on their
 * own page.
 *
 * =============================================================================
 * THE LEDGER IS PER-STUDENT, SO THE ARITHMETIC IS TOO
 * =============================================================================
 *   `GET /fees/summary` answers "what did this CAMPUS bill this month", which is a
 *   different question and cannot be narrowed to one child. So the four figures at
 *   the top are summed here, from this student's own challans — and they follow the
 *   backend's rule exactly: DRAFT and VOID vouchers count towards nothing.
 *
 *   A draft has not been sent to anyone, and a voided challan is not owed. Counting
 *   either would tell the office a family owes money that nobody has asked them for,
 *   which is the one error that ends in an argument at the front desk. The drafts
 *   are still LISTED, because someone has to issue them — they just sit outside the
 *   totals, with their own line saying so.
 *
 * WHY ACTIONS LIVE ON THE ROW
 *   Taking a payment is the single most common thing anyone does after looking up a
 *   student, and making them open the challan first to find the button is one click
 *   and one page load per parent standing at the counter. Every action here is the
 *   same mutation the challan screen fires, guarded by the same permission — this is
 *   a shortcut to them, never a second implementation of them.
 *
 *   Expanding a row is how the detail stays on ONE page: the lines that make up the
 *   bill and the receipts taken against it appear in place, fetched only for the row
 *   actually opened rather than for all of them up front.
 */
export function StudentFeesPanel({
  studentId,
  studentName,
  classId,
  className,
  canIssue,
  canCollect,
  canVoid,
  canManageFees,
}: {
  studentId: string;
  studentName: string;
  /**
   * The class the student sits in, resolved from their section.
   *
   * Handed to the challan dialog so it can find the structure itself. A structure
   * belongs to one class and the student's class is already on the screen — asking an
   * operator to pick it again is a question with a wrong answer available, and the
   * wrong answer bills a child against another grade's fees.
   *
   * `undefined` for an unassigned student, which is the one case where the dialog
   * genuinely has to ask.
   */
  classId?: string;
  className?: string;
  canIssue: boolean;
  canCollect: boolean;
  canVoid: boolean;
  /** `fee:manage` — needed to change what this student is charged, not to see it. */
  canManageFees: boolean;
}) {
  // Newest first: the challan someone is asking about is almost always the last one
  // issued. 100 is the API's ceiling and roughly eight years of monthly billing —
  // `meta.total` is checked below so a longer history says so rather than lying.
  const vouchers = useVouchers({
    student_id: studentId,
    size: 100,
    sort_by: "issue_date",
    sort_dir: "desc",
  });

  const issue = useIssueVoucher();
  const voidVoucher = useVoidVoucher();
  const reverse = useReversePayment();

  const [collecting, setCollecting] = React.useState<FeeVoucherRead | null>(null);
  const [voiding, setVoiding] = React.useState<FeeVoucherRead | null>(null);
  const [voidReason, setVoidReason] = React.useState("");
  const [reversing, setReversing] = React.useState<{ id: string; receipt: string } | null>(null);
  const [reverseReason, setReverseReason] = React.useState("");
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const [generating, setGenerating] = React.useState(false);
  const [selected, setSelected] = React.useState<string[]>([]);

  const items = React.useMemo(() => vouchers.data?.items ?? [], [vouchers.data]);
  const currency = items[0]?.currency ?? "PKR";
  const money = React.useMemo(
    () =>
      new Intl.NumberFormat("en-PK", {
        style: "currency",
        currency,
        maximumFractionDigits: 0,
      }),
    [currency],
  );

  const totals = React.useMemo(() => summarise(items), [items]);

  // Selections are cleared when the list underneath them changes -- a challan voided
  // or paid in another tab would otherwise stay ticked, and the combined print would
  // 422 against a page still showing it as selectable.
  const ids = React.useMemo(() => items.map((v) => v.id).join(","), [items]);
  React.useEffect(() => setSelected([]), [ids]);

  const chosen = React.useMemo(
    () => items.filter((voucher) => selected.includes(voucher.id)),
    [items, selected],
  );

  return (
    <section className="mt-6">
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
        <div>
          <h2 className="text-sm font-medium">Fees</h2>
          <p className="text-xs text-muted-foreground">
            Every challan billed to {studentName}, and what is still owed on each.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {chosen.length > 1 ? (
            /* A real navigation, like the single-challan print: the PDF is a stream
               the browser hands to its own viewer. */
            <Button variant="outline" size="sm" asChild>
              <a
                href={feesApi.vouchers.combinedPdfUrl(chosen.map((voucher) => voucher.id))}
                target="_blank"
                rel="noreferrer"
              >
                <Printer className="size-4" aria-hidden />
                Print {chosen.length} on one challan
              </a>
            </Button>
          ) : null}
          {canIssue ? (
            <Button variant="outline" size="sm" onClick={() => setGenerating(true)}>
              <Receipt className="size-4" aria-hidden />
              Generate a challan
            </Button>
          ) : null}
        </div>
      </div>

      {/* --- The four figures --------------------------------------------- */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Figure
          label="Billed"
          value={money.format(totals.billed)}
          hint={
            totals.drafts > 0
              ? `${totals.drafts} draft${totals.drafts === 1 ? "" : "s"} not counted`
              : `${totals.counted} challan${totals.counted === 1 ? "" : "s"}`
          }
          loading={vouchers.isPending}
        />
        <Figure
          label="Paid"
          value={money.format(totals.paid)}
          tone="success"
          loading={vouchers.isPending}
        />
        <Figure
          label="Outstanding"
          value={money.format(totals.outstanding)}
          tone={totals.outstanding > 0 ? "warning" : undefined}
          loading={vouchers.isPending}
        />
        <Figure
          label="Overdue"
          value={money.format(totals.overdue)}
          hint="Past the due date and unpaid"
          tone={totals.overdue > 0 ? "destructive" : undefined}
          loading={vouchers.isPending}
        />
      </div>

      {/* --- What they are charged -----------------------------------------
          Above the history on purpose: the arrangement explains the challans below
          it, and an operator looking at an unexpected total reads upwards for the
          reason. */}
      <StudentFeeArrangement
        studentId={studentId}
        academicYear={currentAcademicYear()}
        canManage={canManageFees}
      />

      {/* --- The challans -------------------------------------------------- */}
      <Card className="mt-3 overflow-hidden p-0">
        {vouchers.isPending ? (
          <TableCardSkeleton columns={8} />
        ) : vouchers.isError ? (
          <ErrorState error={vouchers.error} onRetry={() => void vouchers.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            icon={Wallet}
            title="Nothing billed yet"
            description={
              canIssue
                ? "This student has no challans. Generate one against an active fee structure for their class."
                : "This student has no challans."
            }
            action={
              canIssue ? (
                <Button onClick={() => setGenerating(true)}>Generate a challan</Button>
              ) : undefined
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8">
                    <span className="sr-only">Select for a combined challan</span>
                  </TableHead>
                  <TableHead className="w-10" />
                  <TableHead>Challan</TableHead>
                  <TableHead>Due</TableHead>
                  <TableHead className="text-end">Total</TableHead>
                  <TableHead className="text-end">Paid</TableHead>
                  <TableHead className="text-end">Outstanding</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-end">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((voucher) => {
                  const outstanding = Number(voucher.outstanding);
                  const isDraft = voucher.status === "draft";
                  const isVoid = voucher.status === "void";
                  const open = expanded === voucher.id;

                  const ticked = selected.includes(voucher.id);

                  return (
                    <React.Fragment key={voucher.id}>
                      <TableRow className={isVoid ? "opacity-60" : undefined}>
                        <TableCell>
                          {/* A VOIDED challan cannot join a combined print -- folding a
                              cancelled charge into a live total asks a family to pay
                              it, and the API refuses. Reprinting one on its own is
                              still available from the row's printer button. */}
                          <input
                            type="checkbox"
                            className="size-3.5 accent-primary disabled:opacity-40"
                            checked={ticked}
                            disabled={isVoid || (!ticked && selected.length >= MAX_COMBINED)}
                            aria-label={`Include ${voucher.voucher_number} in a combined challan`}
                            onChange={(event) =>
                              setSelected((current) =>
                                event.target.checked
                                  ? [...current, voucher.id]
                                  : current.filter((id) => id !== voucher.id),
                              )
                            }
                          />
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-7"
                            aria-expanded={open}
                            aria-label={
                              open
                                ? `Hide ${voucher.voucher_number}`
                                : `Show what ${voucher.voucher_number} charges`
                            }
                            onClick={() => setExpanded(open ? null : voucher.id)}
                          >
                            {open ? (
                              <ChevronDown className="size-4" aria-hidden />
                            ) : (
                              <ChevronRight className="size-4" aria-hidden />
                            )}
                          </Button>
                        </TableCell>

                        <TableCell>
                          <div className="font-mono text-xs">{voucher.voucher_number}</div>
                          <div className="text-xs text-muted-foreground">
                            {voucher.period_label} · {voucher.academic_year}
                          </div>
                        </TableCell>

                        <TableCell className="whitespace-nowrap text-sm">
                          <span
                            className={
                              isOverdue(voucher)
                                ? "text-destructive"
                                : "text-muted-foreground"
                            }
                          >
                            {formatDate(voucher.due_date)}
                          </span>
                        </TableCell>

                        <TableCell className="text-end tabular-nums">
                          {money.format(Number(voucher.total))}
                        </TableCell>
                        <TableCell className="text-end tabular-nums text-muted-foreground">
                          {money.format(Number(voucher.paid_total))}
                        </TableCell>
                        <TableCell className="text-end tabular-nums">
                          {outstanding > 0 && !isVoid && !isDraft ? (
                            <span className="font-medium">{money.format(outstanding)}</span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>

                        <TableCell>
                          <VoucherStatusBadge status={voucher.status} />
                        </TableCell>

                        {/* Every action the challan screen offers, on the row. The
                            conditions are the API's own rules: a draft cannot take
                            money, an issued challan cannot be edited, and a settled
                            one has nothing left to collect. */}
                        <TableCell>
                          <div className="flex items-center justify-end gap-1">
                            {isDraft && canIssue ? (
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={issue.isPending}
                                onClick={() => issue.mutate(voucher.id)}
                              >
                                <Send className="size-3.5" aria-hidden />
                                Issue
                              </Button>
                            ) : null}

                            {!isDraft && !isVoid && outstanding > 0 && canCollect ? (
                              <Button size="sm" onClick={() => setCollecting(voucher)}>
                                <Wallet className="size-3.5" aria-hidden />
                                Pay
                              </Button>
                            ) : null}

                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-8"
                              asChild
                              title="Print challan"
                            >
                              <a
                                href={feesApi.vouchers.pdfUrl(voucher.id)}
                                target="_blank"
                                rel="noreferrer"
                              >
                                <Printer className="size-4" aria-hidden />
                                <span className="sr-only">
                                  Print challan {voucher.voucher_number}
                                </span>
                              </a>
                            </Button>

                            {!isVoid && canVoid ? (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="size-8"
                                title="Void challan"
                                onClick={() => setVoiding(voucher)}
                              >
                                <Ban className="size-4" aria-hidden />
                                <span className="sr-only">
                                  Void challan {voucher.voucher_number}
                                </span>
                              </Button>
                            ) : null}

                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-8"
                              asChild
                              title="Open challan"
                            >
                              <Link href={`/fees/${voucher.id}`}>
                                <ExternalLink className="size-4" aria-hidden />
                                <span className="sr-only">
                                  Open challan {voucher.voucher_number}
                                </span>
                              </Link>
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>

                      {open ? (
                        <TableRow className="hover:bg-transparent">
                          <TableCell colSpan={9} className="bg-muted/30 p-0">
                            <VoucherBreakdown
                              voucherId={voucher.id}
                              currency={currency}
                              canIssue={canIssue}
                              canVoid={canVoid}
                              onReverse={(payment) => setReversing(payment)}
                            />
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </React.Fragment>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>

      {/* The list is capped at the API's page ceiling. Saying so is the difference
          between a complete history and one that merely looks complete. */}
      {vouchers.data && vouchers.data.meta.total > items.length ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Showing the {items.length} most recent of {vouchers.data.meta.total} challans.{" "}
          <Link href="/fees" className="underline underline-offset-2">
            The fees register
          </Link>{" "}
          holds the rest.
        </p>
      ) : null}

      {/* --- Dialogs ------------------------------------------------------- */}
      {canCollect && collecting ? (
        <RecordPaymentDialog
          open
          onOpenChange={(next) => !next && setCollecting(null)}
          voucherId={collecting.id}
          outstanding={Number(collecting.outstanding)}
          currency={collecting.currency}
        />
      ) : null}

      <ReasonDialog
        open={voiding !== null}
        onOpenChange={(next) => !next && setVoiding(null)}
        title={`Void challan ${voiding?.voucher_number ?? ""}?`}
        description="It stops counting towards billed and outstanding, and the student can be billed again for this period. Receipts already recorded against it are kept."
        confirmLabel="Void challan"
        reason={voidReason}
        onReasonChange={setVoidReason}
        busy={voidVoucher.isPending}
        onConfirm={async () => {
          if (!voiding) return;
          await voidVoucher.mutateAsync({ id: voiding.id, reason: voidReason.trim() });
          setVoiding(null);
          setVoidReason("");
        }}
      />

      <ReasonDialog
        open={reversing !== null}
        onOpenChange={(next) => !next && setReversing(null)}
        title={`Reverse receipt ${reversing?.receipt ?? ""}?`}
        description="The receipt stays on the challan, struck through, and the amount goes back to outstanding. Both the original and this reversal keep the name of who recorded them."
        confirmLabel="Reverse receipt"
        reason={reverseReason}
        onReasonChange={setReverseReason}
        busy={reverse.isPending}
        onConfirm={async () => {
          if (!reversing) return;
          await reverse.mutateAsync({ paymentId: reversing.id, reason: reverseReason.trim() });
          setReversing(null);
          setReverseReason("");
        }}
      />

      {canIssue ? (
        <GenerateChallansDialog
          open={generating}
          onOpenChange={setGenerating}
          academicYear={currentAcademicYear()}
          canCollect={canCollect}
          studentIds={[studentId]}
          studentName={studentName}
          classId={classId}
          className={className}
        />
      ) : null}
    </section>
  );
}

/**
 * What one challan charges and what has been received against it.
 *
 * Fetched only when its row is opened — a student with forty challans must not cost
 * forty requests to look at one. TanStack caches the result under the same key the
 * challan page uses, so opening it here warms that page and vice versa.
 */
function VoucherBreakdown({
  voucherId,
  currency,
  canIssue,
  canVoid,
  onReverse,
}: {
  voucherId: string;
  currency: string;
  canIssue: boolean;
  canVoid: boolean;
  onReverse: (payment: { id: string; receipt: string }) => void;
}) {
  const voucher = useVoucher(voucherId);
  const removeCharge = useRemoveVoucherStationery();

  const money = React.useMemo(
    () =>
      new Intl.NumberFormat("en-PK", {
        style: "currency",
        currency,
        maximumFractionDigits: 0,
      }),
    [currency],
  );

  if (voucher.isPending) {
    return <p className="px-5 py-4 text-sm text-muted-foreground">Loading challan…</p>;
  }
  if (voucher.isError) {
    return (
      <div className="p-4">
        <ErrorState error={voucher.error} onRetry={() => void voucher.refetch()} />
      </div>
    );
  }

  const data = voucher.data;
  // A draft is still being assembled, so it is the one state where a line can be
  // added or dropped. The API refuses both once it is issued; this simply does not
  // offer them, so nobody discovers the rule by hitting a 409.
  const isDraft = data.status === "draft";
  const charged = new Set(
    data.items.map((item) => item.stationery_item_id).filter(Boolean) as string[],
  );

  return (
    <div className="grid gap-6 px-5 py-4 md:grid-cols-2">
      <div>
        <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Charges
        </h3>
        <ul className="space-y-1.5 text-sm">
          {data.items.map((item) => (
            <li key={item.id} className="flex items-baseline justify-between gap-4">
              <span>
                {item.line_name}
                {item.line_type === "stationery" ? (
                  <span className="ms-2 text-xs text-muted-foreground">
                    {Number(item.quantity)}{" "}
                    {unitLabel(item.unit_label, Number(item.quantity))} ×{" "}
                    {money.format(Number(item.unit_price))}
                  </span>
                ) : null}
              </span>
              <span className="flex shrink-0 items-center gap-1">
                <span className="tabular-nums">{money.format(Number(item.amount))}</span>
                {isDraft && canIssue && item.line_type === "stationery" ? (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    title="Remove charge"
                    disabled={removeCharge.isPending}
                    onClick={() =>
                      removeCharge.mutate({
                        id: data.id,
                        stationeryItemId: item.stationery_item_id!,
                      })
                    }
                  >
                    <Trash2 className="size-3.5" aria-hidden />
                    <span className="sr-only">Remove {item.line_name}</span>
                  </Button>
                ) : null}
              </span>
            </li>
          ))}
        </ul>

        {isDraft && canIssue ? (
          // The form brings its own top divider, which is exactly the separator
          // wanted here — a second border around it would double the line.
          <div className="mt-3 overflow-hidden rounded-md">
            <AddChargeForm voucherId={data.id} alreadyCharged={charged} />
          </div>
        ) : null}
        {data.notes ? (
          <p className="mt-3 text-xs text-muted-foreground">{data.notes}</p>
        ) : null}
        {data.status === "void" && data.void_reason ? (
          <p className="mt-3 text-xs text-muted-foreground">
            Voided — {data.void_reason}
          </p>
        ) : null}
      </div>

      <div>
        <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Receipts
        </h3>
        {data.payments.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing received against this challan yet.</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {/* Reversed receipts are struck through and KEPT. A reversal is a second
                event, not an undo — which is the whole reason `fee:void` is a
                different permission from `fee:collect`. */}
            {data.payments.map((payment) => {
              const reversed = payment.status === "reversed";
              return (
                <li key={payment.id} className="flex items-baseline justify-between gap-3">
                  <span className={reversed ? "opacity-60" : undefined}>
                    <span className="font-mono text-xs">{payment.receipt_number}</span>
                    <span className="ms-2 text-xs text-muted-foreground">
                      {formatDate(payment.received_on)} ·{" "}
                      {label(PAYMENT_METHOD_LABELS, payment.method)}
                    </span>
                    {reversed ? (
                      <span className="ms-2 text-xs text-destructive">Reversed</span>
                    ) : null}
                  </span>
                  <span className="flex shrink-0 items-center gap-1">
                    <span className={`tabular-nums ${reversed ? "line-through opacity-60" : ""}`}>
                      {money.format(Number(payment.amount))}
                    </span>
                    {canVoid && !reversed ? (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7"
                        title="Reverse receipt"
                        onClick={() =>
                          onReverse({ id: payment.id, receipt: payment.receipt_number })
                        }
                      >
                        <Undo2 className="size-3.5" aria-hidden />
                        <span className="sr-only">
                          Reverse receipt {payment.receipt_number}
                        </span>
                      </Button>
                    ) : null}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

/** Past its due date with money still on it. Drafts and voids can never be. */
function isOverdue(voucher: FeeVoucherRead): boolean {
  if (voucher.status === "draft" || voucher.status === "void") return false;
  if (Number(voucher.outstanding) <= 0) return false;
  return voucher.due_date < new Date().toISOString().slice(0, 10);
}

/**
 * The student's own billed / paid / outstanding / overdue.
 *
 * Mirrors `FeeService.summary` deliberately: DRAFT and VOID are excluded from the
 * money, and outstanding is `billed - paid` rather than a third independent sum —
 * two figures that must agree are guaranteed to agree only when one is derived from
 * the other.
 */
function summarise(vouchers: FeeVoucherRead[]) {
  let billed = 0;
  let paid = 0;
  let overdue = 0;
  let counted = 0;
  let drafts = 0;

  for (const voucher of vouchers) {
    if (voucher.status === "draft") {
      drafts += 1;
      continue;
    }
    if (voucher.status === "void") continue;

    counted += 1;
    billed += Number(voucher.total);
    paid += Number(voucher.paid_total);
    if (isOverdue(voucher)) overdue += Number(voucher.outstanding);
  }

  return { billed, paid, outstanding: billed - paid, overdue, counted, drafts };
}

/**
 * One headline number.
 *
 * Tone sits on the VALUE rather than the card: four coloured cards in a row would
 * compete with the status pills in the table directly beneath them.
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
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {labelText}
      </p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${toneClass}`}>
        {loading ? "—" : value}
      </p>
      {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
    </Card>
  );
}
