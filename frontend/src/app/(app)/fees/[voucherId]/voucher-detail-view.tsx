"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Ban, Printer, Send, Trash2, Undo2, Wallet } from "lucide-react";

import { RecordPaymentDialog } from "@/components/fees/record-payment-dialog";
import { ReasonDialog } from "@/components/fees/reason-dialog";
import { AddChargeForm } from "@/components/fees/add-charge-form";
import { AddFeeChargeForm } from "@/components/fees/add-fee-charge-form";
import { fillNodes } from "@/lib/i18n/format";
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
  useRemoveVoucherFeeCharge,
  useRemoveVoucherStationery,
  useReversePayment,
  useVoidVoucher,
  useVoucher,
} from "@/hooks/use-fees";
import { feesApi } from "@/lib/api/resources/fees";
import { label, type VoucherItemRead } from "@/lib/api/types";
import { fill, ltr } from "@/lib/i18n/format";
import { feesMessages } from "@/lib/i18n/modules/fees";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { useLabels } from "@/lib/i18n/use-labels";
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
  const m = useCatalog(feesMessages).voucher;
  const L = useLabels();
  const voucher = useVoucher(voucherId);
  const issue = useIssueVoucher();
  const voidVoucher = useVoidVoucher();
  const reverse = useReversePayment();
  const removeCharge = useRemoveVoucherStationery();
  const removeFeeLine = useRemoveVoucherFeeCharge();

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
        <ArrowLeft className="size-4 rtl:rotate-180" aria-hidden />
        {m.back}
      </Link>

      <PageHeader
        title={data.student_name}
        description={fill(m.headerDescription, {
          admission: ltr(data.admission_number),
          number: ltr(data.voucher_number),
          period: data.period_label,
        })}
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
                {m.printChallan}
              </a>
            </Button>

            {isDraft && canIssue ? (
              <Button
                size="sm"
                disabled={issue.isPending}
                onClick={() => issue.mutate(data.id)}
              >
                <Send className="size-4" aria-hidden />
                {m.issue}
              </Button>
            ) : null}

            {!isDraft && !isVoid && !settled && canCollect ? (
              <Button size="sm" onClick={() => setCollecting(true)}>
                <Wallet className="size-4" aria-hidden />
                {m.recordPayment}
              </Button>
            ) : null}

            {!isVoid && canVoid ? (
              <Button variant="ghost" size="sm" onClick={() => setVoiding(true)}>
                <Ban className="size-4" aria-hidden />
                {m.void}
              </Button>
            ) : null}
          </div>
        }
      />

      {isVoid ? (
        <p className="mb-6 rounded-md bg-muted px-4 py-3 text-sm">
          <span className="font-medium">
            {data.voided_at
              ? fill(m.voidedOn, { date: formatDateTime(data.voided_at) })
              : m.voided}
          </span>
          {data.void_reason ? ` ${fill(m.voidReason, { reason: data.void_reason })}` : ""}{" "}
          {m.voidedBody}
        </p>
      ) : null}

      {isDraft ? (
        <p className="mb-6 rounded-md bg-warning/15 px-4 py-3 text-sm">{m.draftNotice}</p>
      ) : null}

      {/* THE ONLY ANSWER TO "WHY IS THIS ONE VOID?" THAT DOES NOT NEED A PHONE CALL.
          A superseded challan reads exactly like a cancelled one otherwise, and the
          difference matters at the counter: this money was not written off, it moved
          onto another document the family is still expected to pay. Shown while the
          replacement is still a DRAFT too, where the wording differs because nothing
          has been cancelled yet — the reservation is visible before it bites. */}
      {data.superseded_by_voucher_id ? (
        <p className="mb-6 rounded-md bg-muted px-4 py-3 text-sm">
          <span className="font-medium">{isVoid ? m.carriedTitle : m.reservedTitle}</span>{" "}
          {fillNodes(isVoid ? m.carriedBody : m.reservedBody, {
            link: (
              <Link
                href={`/fees/${data.superseded_by_voucher_id}`}
                className="font-medium underline underline-offset-2"
              >
                {data.superseded_by_voucher_number ?? m.newerChallan}
              </Link>
            ),
          })}
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        {/* --- What was billed ------------------------------------------- */}
        <Card className="overflow-hidden p-0">
          <h2 className="border-b border-border px-5 py-3 text-sm font-medium">{m.charges}</h2>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{m.colLine}</TableHead>
                  <TableHead className="text-end">{m.colAmount}</TableHead>
                  {/* The remove column exists only while the bill is still being
                      assembled, so an issued challan cannot even suggest an edit. */}
                  {isDraft && canIssue ? <TableHead className="w-10" /> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>
                      <ChargeDescription item={item} working={m.stationeryWorking} />
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
                            aria-label={fill(m.removeNamed, { name: item.line_name })}
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
                        ) : item.head_id ? (
                          // A fee line, from the structure or a one-off charge. Taking it
                          // off a DRAFT is how "not paying the exam fee this term" is
                          // said without touching the structure the class bills from.
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={fill(m.removeNamed, { name: item.line_name })}
                            disabled={removeFeeLine.isPending}
                            onClick={() =>
                              removeFeeLine.mutate({ id: data.id, headId: item.head_id! })
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
            <>
              <AddFeeChargeForm
                voucherId={data.id}
                currency={data.currency}
                chargedHeadIds={
                  new Set(
                    data.items
                      .filter((item) => item.line_type === "fee")
                      .map((item) => item.head_id)
                      .filter(Boolean) as string[],
                  )
                }
              />
              <AddChargeForm
                voucherId={data.id}
                alreadyCharged={new Set(
                  data.items.map((item) => item.stationery_item_id).filter(Boolean) as string[],
                )}
              />
            </>
          ) : null}
          <dl className="grid gap-2 border-t border-border px-5 py-4 text-sm">
            <Row term={m.total} value={money.format(Number(data.total))} strong />
            <Row term={m.received} value={money.format(Number(data.paid_total))} />
            <Row
              term={m.outstanding}
              value={money.format(outstanding)}
              strong
              tone={outstanding > 0 ? "owed" : "clear"}
            />
          </dl>
        </Card>

        {/* --- Dates ------------------------------------------------------- */}
        <Card className="p-5">
          <h2 className="text-sm font-medium">{m.dates}</h2>
          <dl className="mt-3 grid gap-2 text-sm">
            <Row term={m.issuedOn} value={formatDate(data.issue_date)} />
            <Row term={m.due} value={formatDate(data.due_date)} />
            <Row term={m.academicYear} value={data.academic_year} />
            <Row term={m.description} value={data.period_label} />
            {data.paid_at ? <Row term={m.settled} value={formatDateTime(data.paid_at)} /> : null}
          </dl>
        </Card>
      </div>

      {/* --- Receipts ------------------------------------------------------ */}
      <Card className="mt-4 overflow-hidden p-0">
        <h2 className="border-b border-border px-5 py-3 text-sm font-medium">{m.receipts}</h2>
        {data.payments.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-muted-foreground">{m.noReceipts}</p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{m.colReceipt}</TableHead>
                  <TableHead>{m.colReceived}</TableHead>
                  <TableHead>{m.colMethod}</TableHead>
                  <TableHead className="text-end">{m.colAmount}</TableHead>
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
                            {m.reversed}
                          </span>
                        ) : null}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                        {formatDate(payment.received_on)}
                      </TableCell>
                      <TableCell className="text-sm">
                        {label(L.paymentMethod, payment.method)}
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
                              aria-label={fill(m.reverseNamed, {
                                receipt: payment.receipt_number,
                              })}
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
        title={m.voidTitle}
        description={m.voidDescription}
        confirmLabel={m.voidConfirm}
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
        title={fill(m.reverseTitle, { receipt: reversing?.receipt ?? "" })}
        description={m.reverseDescription}
        confirmLabel={m.reverseConfirm}
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
function ChargeDescription({ item, working }: { item: VoucherItemRead; working: string }) {
  const { unit } = useLabels();
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
        {fill(working, {
          qty: quantity,
          unit: unit(item.unit_label, quantity),
          price: money.format(Number(item.unit_price)),
        })}
      </span>
    </>
  );
}
