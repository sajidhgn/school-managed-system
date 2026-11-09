"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { useAddVoucherFeeCharge, useFeeHeads } from "@/hooks/use-fees";
import { fill } from "@/lib/i18n/format";
import { feesMessages } from "@/lib/i18n/modules/fees";
import { useCatalog } from "@/lib/i18n/use-catalog";

/**
 * Charge a fee head to ONE student's draft challan — a fine, a re-exam fee, a broken
 * lab window.
 *
 * =============================================================================
 * WHY THIS IS NOT DONE ON THE CLASS STRUCTURE
 * =============================================================================
 *   Without this, "charge Ali 500 for the window" means adding a Breakage line to
 *   Grade 7's structure, generating, and removing it next month — which bills all
 *   forty children for one window, and the parents find the mistake first.
 *
 * A head already on the challan (from the class structure) can be picked too: that
 * RESTATES the line, which is how one student's exam fee is changed on a bill still
 * being assembled. The picker says so beside the head's name, so nobody is surprised
 * when the line they expected to add turns into the line they already had.
 *
 * Inline, like the stationery form beside it, because the office works through a
 * register several students in a row.
 */
export function AddFeeChargeForm({
  voucherId,
  chargedHeadIds,
  currency,
}: {
  voucherId: string;
  /** Heads already on this challan, so the picker can warn that it will restate. */
  chargedHeadIds: Set<string>;
  currency: string;
}) {
  const m = useCatalog(feesMessages).feeCharge;
  const heads = useFeeHeads({ size: 100 });
  const addCharge = useAddVoucherFeeCharge();

  const [headId, setHeadId] = React.useState("");
  const [amount, setAmount] = React.useState("");
  const [note, setNote] = React.useState("");

  const active = (heads.data?.items ?? []).filter((head) => head.is_active);
  const amountValue = Number(amount);
  const validAmount = amount.trim() !== "" && Number.isFinite(amountValue) && amountValue >= 0;
  const restating = headId !== "" && chargedHeadIds.has(headId);

  if (heads.isPending || active.length === 0) return null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!headId || !validAmount) return;
    await addCharge.mutateAsync({
      id: voucherId,
      body: {
        head_id: headId,
        amount: amountValue.toFixed(2),
        note: note.trim() || null,
      },
    });
    setHeadId("");
    setAmount("");
    setNote("");
  }

  return (
    <form
      onSubmit={submit}
      className="grid gap-2 border-t border-border bg-muted/30 p-4"
      aria-label={m.label}
    >
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid min-w-44 flex-1 gap-1.5 text-sm">
          <span className="text-xs font-medium">{m.label}</span>
          <NativeSelect value={headId} onChange={(event) => setHeadId(event.target.value)}>
            <option value="">{m.chooseHead}</option>
            {active.map((head) => (
              <option key={head.id} value={head.id}>
                {chargedHeadIds.has(head.id) ? fill(m.alreadyOn, { name: head.name }) : head.name}
              </option>
            ))}
          </NativeSelect>
        </label>
        <label className="grid w-32 gap-1.5 text-sm">
          <span className="text-xs font-medium">{fill(m.amount, { currency })}</span>
          <Input
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            inputMode="decimal"
            placeholder="500"
          />
        </label>
        <label className="grid min-w-44 flex-1 gap-1.5 text-sm">
          <span className="text-xs font-medium">{m.note}</span>
          <Input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            maxLength={255}
            placeholder={m.notePlaceholder}
          />
        </label>
        <Button
          type="submit"
          variant="outline"
          loading={addCharge.isPending}
          disabled={!headId || !validAmount}
        >
          {restating ? m.changeLine : m.submit}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{restating ? m.restatingHelp : m.help}</p>
    </form>
  );
}
