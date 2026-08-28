"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { useAddVoucherStationery, useStationeryItems } from "@/hooks/use-fees";
import { STATIONERY_UNIT_LABELS, label } from "@/lib/api/types";

/**
 * Charge a stationery article to this student's draft challan.
 *
 * Inline rather than in a dialog, deliberately: the office adds these while walking a
 * class register, several students in a row, and a modal that has to be opened and
 * dismissed per student is the flow people abandon halfway. Articles already on the
 * challan are filtered out of the picker, so the quantity is changed by removing and
 * re-adding rather than by two controls that do nearly the same thing.
 */
export function AddChargeForm({
  voucherId,
  alreadyCharged,
}: {
  voucherId: string;
  alreadyCharged: Set<string>;
}) {
  const stationery = useStationeryItems({ size: 100, active_only: true });
  const addCharge = useAddVoucherStationery();

  const [itemId, setItemId] = React.useState("");
  const [quantity, setQuantity] = React.useState("1");

  const available = (stationery.data?.items ?? []).filter((item) => !alreadyCharged.has(item.id));
  const money = new Intl.NumberFormat("en-PK", {
    style: "currency",
    currency: "PKR",
    maximumFractionDigits: 0,
  });

  if (stationery.isPending) return null;
  if (stationery.data && stationery.data.items.length === 0) {
    return (
      <p className="border-t border-border px-5 py-4 text-xs text-muted-foreground">
        Nothing in the stationery catalog yet. Add copies, pencils and books under
        Charges &amp; structures to bill them here.
      </p>
    );
  }
  if (available.length === 0) return null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!itemId || !quantity.trim()) return;
    // The price is not sent: the catalog's price applies, which is what makes the
    // ordinary path impossible to get wrong.
    await addCharge.mutateAsync({
      id: voucherId,
      body: { stationery_item_id: itemId, quantity: quantity.trim() },
    });
    setItemId("");
    setQuantity("1");
  }

  return (
    <form
      onSubmit={submit}
      className="flex flex-wrap items-end gap-2 border-t border-border bg-muted/30 p-4"
    >
      <label className="grid flex-1 gap-1.5 text-sm">
        <span className="text-xs font-medium">Add stationery</span>
        <NativeSelect value={itemId} onChange={(event) => setItemId(event.target.value)}>
          <option value="">Choose…</option>
          {available.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} — {money.format(Number(item.unit_price))} /{" "}
              {label(STATIONERY_UNIT_LABELS, item.unit)}
            </option>
          ))}
        </NativeSelect>
      </label>
      <label className="grid w-24 gap-1.5 text-sm">
        <span className="text-xs font-medium">Qty</span>
        <Input
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          inputMode="decimal"
          placeholder="1"
        />
      </label>
      <Button type="submit" variant="outline" disabled={addCharge.isPending || !itemId}>
        Add charge
      </Button>
      <p className="w-full text-xs text-muted-foreground">
        Only while this is a draft. Once issued the challan is final — put anything else
        on the student&rsquo;s next one.
      </p>
    </form>
  );
}
