"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
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
import { useRecordPayment } from "@/hooks/use-fees";
import { PAYMENT_METHOD_LABELS, type PaymentMethod } from "@/lib/api/types";

/**
 * Take money against a challan.
 *
 * =============================================================================
 * PART PAYMENT IS THE NORMAL CASE, NOT AN EDGE CASE
 * =============================================================================
 *   Fees are often paid in instalments, so the amount defaults to the full
 *   outstanding balance but stays editable, and paying less is not treated as an
 *   error — the challan simply moves to "part paid" and keeps a balance. What IS
 *   refused is paying MORE than is owed: an overpayment is a different transaction
 *   with different accounting, and silently accepting one here would leave a negative
 *   balance nobody asked for.
 *
 * There is no undo on this dialog. A mis-keyed receipt is corrected by REVERSING it,
 * which requires `fee:void` and leaves both entries visible — that separation is the
 * module's whole reason for splitting the two permissions.
 */
export function RecordPaymentDialog({
  open,
  onOpenChange,
  voucherId,
  outstanding,
  currency,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  voucherId: string;
  outstanding: number;
  currency: string;
}) {
  const record = useRecordPayment();

  const [amount, setAmount] = React.useState(String(outstanding));
  const [method, setMethod] = React.useState<PaymentMethod>("cash");
  const [reference, setReference] = React.useState("");
  const [receivedOn, setReceivedOn] = React.useState(() =>
    new Date().toISOString().slice(0, 10),
  );

  // Re-arm the form each time it opens: the balance may have changed since the last
  // receipt, and a stale amount here is money recorded wrongly.
  React.useEffect(() => {
    if (open) {
      setAmount(String(outstanding));
      setMethod("cash");
      setReference("");
      setReceivedOn(new Date().toISOString().slice(0, 10));
    }
  }, [open, outstanding]);

  const parsed = Number(amount);
  const invalid = !Number.isFinite(parsed) || parsed <= 0;
  const overpaid = Number.isFinite(parsed) && parsed > outstanding;
  const part = Number.isFinite(parsed) && parsed > 0 && parsed < outstanding;

  const money = new Intl.NumberFormat("en-PK", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (invalid || overpaid) return;
    await record.mutateAsync({
      id: voucherId,
      body: {
        amount: parsed,
        method,
        received_on: receivedOn,
        ...(reference.trim() ? { reference: reference.trim() } : {}),
      },
    });
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <DialogHeader>
            <DialogTitle>Record a payment</DialogTitle>
            <DialogDescription>
              {money.format(outstanding)} outstanding. A receipt number is issued
              automatically.
            </DialogDescription>
          </DialogHeader>

          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">Amount received</span>
            <Input
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              inputMode="decimal"
              aria-invalid={invalid || overpaid || undefined}
              autoFocus
              required
            />
            {overpaid ? (
              <span className="text-xs text-destructive">
                That is more than the {money.format(outstanding)} owed on this challan.
              </span>
            ) : part ? (
              <span className="text-xs text-muted-foreground">
                Part payment — {money.format(outstanding - parsed)} will remain owing.
              </span>
            ) : null}
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">Method</span>
              <NativeSelect
                value={method}
                onChange={(event) => setMethod(event.target.value as PaymentMethod)}
              >
                {Object.entries(PAYMENT_METHOD_LABELS).map(([value, text]) => (
                  <option key={value} value={value}>
                    {text}
                  </option>
                ))}
              </NativeSelect>
            </label>

            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">Received on</span>
              <Input
                type="date"
                value={receivedOn}
                onChange={(event) => setReceivedOn(event.target.value)}
                required
              />
            </label>
          </div>

          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">Reference</span>
            <Input
              value={reference}
              onChange={(event) => setReference(event.target.value)}
              placeholder="Cheque or transaction number — optional"
            />
          </label>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={record.isPending || invalid || overpaid}>
              {record.isPending ? "Recording…" : "Record payment"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
