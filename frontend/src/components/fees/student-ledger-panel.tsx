"use client";

import * as React from "react";
import { BookText, Scale } from "lucide-react";

import { EmptyState, ErrorState, TableCardSkeleton } from "@/components/data-states";
import { Pagination } from "@/components/pagination";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { fillNodes } from "@/lib/i18n/format";
import { useAdjustLedger, useStudentLedger } from "@/hooks/use-fees";
import { currentAcademicYear } from "@/lib/academic-year";
import { label } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { feesStudentMessages } from "@/lib/i18n/modules/fees-student";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { formatDate } from "@/lib/utils";

const PAGE_SIZE = 10;

/**
 * The student's running account — the statement a family asks for at the counter.
 *
 * =============================================================================
 * THE BALANCE CAN BE NEGATIVE, AND THAT IS NOT A BUG
 * =============================================================================
 *   A negative balance means the school is holding the family's money: an advance,
 *   or a refund owed after a reversal. It is shown as "In credit" rather than clamped
 *   to zero, because clamping would hide money the school has to give back.
 *
 * Every row is an append-only movement — challans, payments, reversals, voids, late
 * fees — with the balance after it, so the statement reads like a bank passbook. The
 * challan table above answers "what is owed on each bill"; this answers "how did the
 * family get to this number".
 *
 * "Adjust balance" is `fee:void`, not `fee:collect`: it is the one movement with no
 * challan or receipt behind it, which makes it the one that could cover a shortfall.
 */
export function StudentLedgerPanel({
  studentId,
  canAdjust,
}: {
  studentId: string;
  /** `fee:void`. */
  canAdjust: boolean;
}) {
  const m = useCatalog(feesStudentMessages).ledger;
  const [page, setPage] = React.useState(1);
  const [adjusting, setAdjusting] = React.useState(false);
  const ledger = useStudentLedger(studentId, { page, size: PAGE_SIZE });

  const money = new Intl.NumberFormat("en-PK", {
    style: "currency",
    currency: "PKR",
    maximumFractionDigits: 0,
  });

  const balance = ledger.data ? Number(ledger.data.balance) : 0;

  return (
    <section className="mt-6">
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
        <div>
          <h2 className="text-sm font-medium">{m.title}</h2>
          <p className="text-xs text-muted-foreground">{m.intro}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {ledger.data ? (
            <div className="text-end">
              <p className="text-xs text-muted-foreground">
                {balance > 0 ? m.owes : balance < 0 ? m.inCredit : m.balance}
              </p>
              <p
                className={`text-lg font-semibold tabular-nums ${
                  balance > 0
                    ? "text-warning-foreground dark:text-warning"
                    : balance < 0
                      ? "text-success"
                      : ""
                }`}
              >
                {money.format(Math.abs(balance))}
              </p>
            </div>
          ) : null}
          {canAdjust ? (
            <Button variant="outline" size="sm" onClick={() => setAdjusting(true)}>
              <Scale className="size-4" aria-hidden />
              {m.adjustBalance}
            </Button>
          ) : null}
        </div>
      </div>

      <Card className="overflow-hidden p-0">
        {ledger.isPending ? (
          <TableCardSkeleton columns={5} />
        ) : ledger.isError ? (
          <ErrorState error={ledger.error} onRetry={() => void ledger.refetch()} />
        ) : ledger.data.entries.length === 0 ? (
          <EmptyState
            icon={BookText}
            title={m.emptyTitle}
            description={m.emptyDescription}
          />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{m.colDate}</TableHead>
                  <TableHead>{m.colEntry}</TableHead>
                  <TableHead className="text-end">{m.colCharged}</TableHead>
                  <TableHead className="text-end">{m.colCredited}</TableHead>
                  <TableHead className="text-end">{m.colBalance}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {ledger.data.entries.map((entry) => {
                  const amount = Number(entry.amount);
                  const after = Number(entry.balance_after);
                  return (
                    <TableRow key={entry.id}>
                      <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                        {formatDate(entry.occurred_on)}
                      </TableCell>
                      <TableCell className="text-sm">
                        <span className="font-medium">{label(m.entry, entry.entry_type)}</span>
                        <span className="block text-xs text-muted-foreground">
                          {entry.description}
                        </span>
                      </TableCell>
                      <TableCell className="text-end tabular-nums">
                        {amount > 0 ? money.format(amount) : ""}
                      </TableCell>
                      <TableCell className="text-end tabular-nums text-success">
                        {amount < 0 ? money.format(-amount) : ""}
                      </TableCell>
                      <TableCell className="text-end font-medium tabular-nums">
                        {after < 0
                          ? fill(m.creditBalance, { amount: money.format(-after) })
                          : money.format(after)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>

      {ledger.data && ledger.data.total_entries > PAGE_SIZE ? (
        <div className="mt-3">
          <Pagination
            meta={{
              page,
              size: PAGE_SIZE,
              total: ledger.data.total_entries,
              pages: Math.ceil(ledger.data.total_entries / PAGE_SIZE),
              has_prev: page > 1,
              has_next: page * PAGE_SIZE < ledger.data.total_entries,
            }}
            onPageChange={setPage}
            disabled={ledger.isFetching}
          />
        </div>
      ) : null}

      {canAdjust ? (
        <AdjustLedgerDialog
          open={adjusting}
          onOpenChange={setAdjusting}
          studentId={studentId}
          studentName={ledger.data?.student_name ?? m.studentFallback}
          balance={balance}
        />
      ) : null}
    </section>
  );
}

/** Today in the browser's own timezone — `toISOString()` would give UTC's date. */
function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/**
 * Write a balance off, or charge one the challans missed.
 *
 * Direction is a choice of two words rather than a signed number field: "-1500" typed
 * as "1500" would bill a family instead of crediting them, and the dialog cannot tell
 * which was meant. The reason is required — an unexplained adjustment is the one entry
 * nobody can audit later.
 */
function AdjustLedgerDialog({
  open,
  onOpenChange,
  studentId,
  studentName,
  balance,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  studentId: string;
  studentName: string;
  balance: number;
}) {
  const m = useCatalog(feesStudentMessages).adjust;
  const adjust = useAdjustLedger(studentId);
  const [direction, setDirection] = React.useState<"credit" | "charge">("credit");
  const [amount, setAmount] = React.useState("");
  const [occurredOn, setOccurredOn] = React.useState(localToday);
  const [academicYear, setAcademicYear] = React.useState(currentAcademicYear);
  const [description, setDescription] = React.useState("");

  React.useEffect(() => {
    if (open) {
      setDirection("credit");
      setAmount("");
      setOccurredOn(localToday());
      setAcademicYear(currentAcademicYear());
      setDescription("");
    }
  }, [open]);

  const parsed = Number(amount);
  const validAmount = amount.trim() !== "" && Number.isFinite(parsed) && parsed > 0;
  const validYear = /^\d{4}-\d{4}$/.test(academicYear.trim());
  const valid = validAmount && validYear && description.trim().length > 0;
  const signed = direction === "credit" ? -parsed : parsed;

  const money = new Intl.NumberFormat("en-PK", {
    style: "currency",
    currency: "PKR",
    maximumFractionDigits: 0,
  });
  const after = balance + (validAmount ? signed : 0);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) return;
    await adjust.mutateAsync({
      amount: signed.toFixed(2),
      academic_year: academicYear.trim(),
      occurred_on: occurredOn || null,
      description: description.trim(),
    });
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <DialogHeader>
            <DialogTitle>{fill(m.title, { name: studentName })}</DialogTitle>
            <DialogDescription>{m.description}</DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">{m.type}</span>
              <NativeSelect
                value={direction}
                onChange={(event) => setDirection(event.target.value as "credit" | "charge")}
              >
                <option value="credit">{m.credit}</option>
                <option value="charge">{m.charge}</option>
              </NativeSelect>
            </label>
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">{m.amountPkr}</span>
              <Input
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                inputMode="decimal"
                placeholder="1500"
                autoFocus
              />
            </label>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">{m.date}</span>
              <Input
                type="date"
                value={occurredOn}
                max={localToday()}
                onChange={(event) => setOccurredOn(event.target.value)}
              />
            </label>
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">{m.academicYear}</span>
              <Input
                value={academicYear}
                onChange={(event) => setAcademicYear(event.target.value)}
                placeholder="2026-2027"
                aria-invalid={!validYear || undefined}
              />
            </label>
          </div>

          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">{m.reason}</span>
            <Input
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              maxLength={255}
              placeholder={m.reasonPlaceholder}
            />
          </label>

          {validAmount ? (
            <p className="rounded-md bg-muted/50 px-3 py-2 text-sm">
              {fillNodes(m.balanceChange, {
                from: (
                  <span className="font-medium tabular-nums">
                    {signedBalance(balance, money, m)}
                  </span>
                ),
                to: (
                  <span className="font-medium tabular-nums">{signedBalance(after, money, m)}</span>
                ),
              })}
            </p>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {m.cancel}
            </Button>
            <Button type="submit" loading={adjust.isPending} disabled={!valid}>
              {m.submit}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function signedBalance(
  value: number,
  money: Intl.NumberFormat,
  copy: { inCredit: string; owed: string },
): string {
  if (value < 0) return fill(copy.inCredit, { amount: money.format(-value) });
  return fill(copy.owed, { amount: money.format(value) });
}
