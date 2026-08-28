"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Ban, Printer, Send, Trash2, Undo2, Wallet } from "lucide-react";

import { RecordPaymentDialog } from "@/components/fees/record-payment-dialog";
import { ReasonDialog } from "@/components/fees/reason-dialog";
import { AddChargeForm } from "@/components/fees/add-charge-form";
import { ErrorState, PageSpinner } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
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
} from "@/hooks/use-fees";
import { feesApi } from "@/lib/api/resources/fees";
import {
  PAYMENT_METHOD_LABELS,
  label,
  unitLabel,
  type VoucherItemRead,
} from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/utils";

/**
 * One challan: what was billed, what has been received, and what is still owed.
 *
 * =============================================================================
 * THE RECEIPTS ARE THE POINT OF THIS SCREEN
 * =============================================================================
 *   A voucher's amounts are a snapshot taken when it was generated — renaming a fee
 *   head, repricing a structure or repricing a stationery item afterwards never
 *   rewrites an issued challan, which is what makes it a document rather than a view.
 *
 *   A DRAFT is the one exception, and it is not really one: a draft bills nothing and
 *   collects nothing, so it is still being assembled rather than being restated. That
 *   is where "Ali also took two more copies" is charged, and the moment it is issued
 *   the charges section disappears and the lines are final. From then on the only
 *   thing that changes here is the payment history below them.
 *
 *   Reversed receipts are struck through and kept, never removed. A reversal is a
 *   second event, not an undo: both the original and the reversal carry a name and a
 *   timestamp, which is the entire reason `fee:void` is separate from `fee:collect`.
 */
export function VoucherDetailView({
  voucherId,
  canIssue,
  canCollect,
  canVoid,
}: {
  voucherId: string;
  canIssue: boolean;
  canCollect: boolean;
  canVoid: boolean;
}) {
  const voucher = useVoucher(voucherId);
  const issue = useIssueVoucher();
  const voidVoucher = useVoidVoucher();
  const reverse = useReversePayment();
  const removeCharge = useRemoveVoucherStationery();

  const [collecting, setCollecting] = React.useState(false);
  const [voiding, setVoiding] = React.useState(false);
  const [voidReason, setVoidReason] = React.useState("");
  const [reversing, setReversing] = React.useState<{ id: string; receipt: string } | null>(null);
  const [reverseReason, setReverseReason] = React.useState("");

  if (voucher.isPending) return <PageSpinner />;
  if (voucher.isError) {
    return (
      <div className="mx-auto w-full max-w-4xl">
        <ErrorState error={voucher.error} onRetry={() => void voucher.refetch()} />
      </div>
    );
  }

  const data = voucher.data;
  const money = new Intl.NumberFormat("en-PK", {
    style: "currency",
    currency: data.currency,
    maximumFractionDigits: 0,
  });

  const outstanding = Number(data.outstanding);
  const isDraft = data.status === "draft";
  const isVoid = data.status === "void";
  const settled = outstanding <= 0;

  return (
    <div className="mx-auto w-full max-w-4xl">
      <Link
        href="/fees"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Fees
      </Link>

      <PageHeader
        title={data.student_name}
        description={`${data.admission_number} · challan ${data.voucher_number} · ${data.period_label}`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <VoucherStatusBadge status={data.status} />

            {/* A real navigation, not a fetch: the PDF is a stream the browser should
                hand to its own viewer. Fetching it into memory to re-offer it as a
                blob would break printing on exactly the devices a school office
                uses. */}
            <Button variant="outline" size="sm" asChild>
              <a href={feesApi.vouchers.pdfUrl(data.id)} target="_blank" rel="noreferrer">
                <Printer className="size-4" aria-hidden />
                Print challan
              </a>
            </Button>

            {isDraft && canIssue ? (
              <Button
                size="sm"
                disabled={issue.isPending}
                onClick={() => issue.mutate(data.id)}
              >
                <Send className="size-4" aria-hidden />
                Issue
              </Button>
            ) : null}

            {!isDraft && !isVoid && !settled && canCollect ? (
              <Button size="sm" onClick={() => setCollecting(true)}>
                <Wallet className="size-4" aria-hidden />
                Record payment
              </Button>
            ) : null}

            {!isVoid && canVoid ? (
              <Button variant="ghost" size="sm" onClick={() => setVoiding(true)}>
                <Ban className="size-4" aria-hidden />
                Void
              </Button>
            ) : null}
          </div>
        }
      />

      {isVoid ? (
        <p className="mb-6 rounded-md bg-muted px-4 py-3 text-sm">
          <span className="font-medium">This challan was voided</span>
          {data.voided_at ? ` on ${formatDateTime(data.voided_at)}` : ""}.
          {data.void_reason ? ` Reason: ${data.void_reason}` : ""} It no longer counts
          towards billed or outstanding, and the student can be billed again for this
          period.
        </p>
      ) : null}

      {isDraft ? (
        <p className="mb-6 rounded-md bg-warning/15 px-4 py-3 text-sm">
          This is a draft. It bills nothing and collects nothing until it is issued.
        </p>
      ) : null}

      {/* THE ONLY ANSWER TO "WHY IS THIS ONE VOID?" THAT DOES NOT NEED A PHONE CALL.
          A superseded challan reads exactly like a cancelled one otherwise, and the
          difference matters at the counter: this money was not written off, it moved
          onto another document the family is still expected to pay. Shown while the
          replacement is still a DRAFT too, where the wording differs because nothing
          has been cancelled yet — the reservation is visible before it bites. */}
      {data.superseded_by_voucher_id ? (
        <p className="mb-6 rounded-md bg-muted px-4 py-3 text-sm">
          <span className="font-medium">
            {isVoid ? "Carried onto a later challan" : "Reserved by a later challan"}
          </span>{" "}
          {isVoid
            ? "What was owed here is billed on"
            : "This is still payable. It will be cancelled, and what is owed here billed on,"}{" "}
          <Link
            href={`/fees/${data.superseded_by_voucher_id}`}
            className="font-medium underline underline-offset-2"
          >
            {data.superseded_by_voucher_number ?? "the newer challan"}
          </Link>
          {isVoid ? "." : " when that challan is issued."}
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        {/* --- What was billed ------------------------------------------- */}
        <Card className="overflow-hidden p-0">
          <h2 className="border-b border-border px-5 py-3 text-sm font-medium">Charges</h2>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Line</TableHead>
                  <TableHead className="text-end">Amount</TableHead>
                  {/* The remove column exists only while the bill is still being
                      assembled, so an issued challan cannot even suggest an edit. */}
                  {isDraft && canIssue ? <TableHead className="w-10" /> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>
                      <ChargeDescription item={item} />
                    </TableCell>
                    <TableCell className="text-end tabular-nums">
                      {money.format(Number(item.amount))}
                    </TableCell>
                    {isDraft && canIssue ? (
                      <TableCell>
                        {item.line_type === "stationery" ? (
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Remove ${item.line_name}`}
                            disabled={removeCharge.isPending}
                            onClick={() =>
                              removeCharge.mutate({
                                id: data.id,
                                stationeryItemId: item.stationery_item_id!,
                              })
                            }
                          >
                            <Trash2 className="size-4" aria-hidden />
                          </Button>
                        ) : null}
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* --- Charge something extra to this one student ---------------
              Draft only. An issued bill is in a parent's hands and is never
              restated — the API refuses it too, this just does not offer it. */}
          {isDraft && canIssue ? (
            <AddChargeForm
              voucherId={data.id}
              alreadyCharged={new Set(
                data.items.map((item) => item.stationery_item_id).filter(Boolean) as string[],
              )}
            />
          ) : null}
          <dl className="grid gap-2 border-t border-border px-5 py-4 text-sm">
            <Row term="Total" value={money.format(Number(data.total))} strong />
            <Row term="Received" value={money.format(Number(data.paid_total))} />
            <Row
              term="Outstanding"
              value={money.format(outstanding)}
              strong
              tone={outstanding > 0 ? "owed" : "clear"}
            />
          </dl>
        </Card>

        {/* --- Dates ------------------------------------------------------- */}
        <Card className="p-5">
          <h2 className="text-sm font-medium">Dates</h2>
          <dl className="mt-3 grid gap-2 text-sm">
            <Row term="Issued on" value={formatDate(data.issue_date)} />
            <Row term="Due" value={formatDate(data.due_date)} />
            <Row term="Academic year" value={data.academic_year} />
            <Row term="Description" value={data.period_label} />
            {data.paid_at ? <Row term="Settled" value={formatDateTime(data.paid_at)} /> : null}
          </dl>
        </Card>
      </div>

      {/* --- Receipts ------------------------------------------------------ */}
      <Card className="mt-4 overflow-hidden p-0">
        <h2 className="border-b border-border px-5 py-3 text-sm font-medium">Receipts</h2>
        {data.payments.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-muted-foreground">
            Nothing received against this challan yet.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Receipt</TableHead>
                  <TableHead>Received</TableHead>
                  <TableHead>Method</TableHead>
                  <TableHead className="text-end">Amount</TableHead>
                  {canVoid ? <TableHead className="w-10" /> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.payments.map((payment) => {
                  const reversed = payment.status === "reversed";
                  return (
                    <TableRow key={payment.id} className={reversed ? "opacity-60" : undefined}>
                      <TableCell className="font-mono text-xs">
                        {payment.receipt_number}
                        {reversed ? (
                          <span className="ms-2 font-sans text-xs text-destructive">
                            Reversed
                          </span>
                        ) : null}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                        {formatDate(payment.received_on)}
                      </TableCell>
                      <TableCell className="text-sm">
                        {label(PAYMENT_METHOD_LABELS, payment.method)}
                        {payment.reference ? (
                          <span className="block text-xs text-muted-foreground">
                            {payment.reference}
                          </span>
                        ) : null}
                      </TableCell>
                      <TableCell
                        className={`text-end tabular-nums ${reversed ? "line-through" : ""}`}
                      >
                        {money.format(Number(payment.amount))}
                      </TableCell>
                      {canVoid ? (
                        <TableCell>
                          {reversed ? null : (
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label={`Reverse receipt ${payment.receipt_number}`}
                              onClick={() =>
                                setReversing({
                                  id: payment.id,
                                  receipt: payment.receipt_number,
                                })
                              }
                            >
                              <Undo2 className="size-4" aria-hidden />
                            </Button>
                          )}
                        </TableCell>
                      ) : null}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>

      {canCollect ? (
        <RecordPaymentDialog
          open={collecting}
          onOpenChange={setCollecting}
          voucherId={data.id}
          outstanding={outstanding}
          currency={data.currency}
        />
      ) : null}

      {/* Void and reverse both demand a written reason, because the reason is the
          only thing the audit row can show a future reader that the amounts cannot. */}
      <ReasonDialog
        open={voiding}
        onOpenChange={setVoiding}
        title="Void this challan?"
        description="It stops counting towards billed and outstanding, and the student can be billed again for this period. Receipts already recorded against it are kept."
        confirmLabel="Void challan"
        reason={voidReason}
        onReasonChange={setVoidReason}
        busy={voidVoucher.isPending}
        onConfirm={async () => {
          await voidVoucher.mutateAsync({ id: data.id, reason: voidReason.trim() });
          setVoiding(false);
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
          await reverse.mutateAsync({
            paymentId: reversing.id,
            reason: reverseReason.trim(),
          });
          setReversing(null);
          setReverseReason("");
        }}
      />

    </div>
  );
}

function Row({
  term,
  value,
  strong,
  tone,
}: {
  term: string;
  value: string;
  strong?: boolean;
  tone?: "owed" | "clear";
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-muted-foreground">{term}</dt>
      <dd
        className={`tabular-nums ${strong ? "font-semibold" : ""} ${
          tone === "owed" ? "text-warning-foreground dark:text-warning" : ""
        } ${tone === "clear" ? "text-success" : ""}`}
      >
        {value}
      </dd>
    </div>
  );
}

/**
 * One line's description, with a stationery line showing its working.
 *
 * "Copy (100 pg) — 3 pieces × PKR 60" rather than a bare "Copy", and for the same
 * reason the printed challan does it: a parent handed a line reading only "Copy —
 * 180" has no way to check it, and the office has no way to answer them. Everything
 * here is the SNAPSHOT the challan was generated with, not the catalog's current
 * wording — which is why the unit comes from `unit_label` on the line rather than
 * from the item it points at.
 */
function ChargeDescription({ item }: { item: VoucherItemRead }) {
  if (item.line_type !== "stationery") return <>{item.line_name}</>;

  const quantity = Number(item.quantity);
  const money = new Intl.NumberFormat("en-PK", {
    style: "currency",
    currency: "PKR",
    maximumFractionDigits: 0,
  });

  return (
    <>
      {item.line_name}
      <span className="ms-2 text-xs text-muted-foreground">
        {quantity} {unitLabel(item.unit_label, quantity)} × {money.format(Number(item.unit_price))}
      </span>
    </>
  );
}
