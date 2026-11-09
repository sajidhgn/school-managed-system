"use client";

import { labelsMessages } from "./modules/labels";
import { useCatalog } from "./use-catalog";

/**
 * Enum display labels in the viewer's language, plus the stationery unit with the
 * right number: `unit("piece", 3)` is "pieces" in English and "عدد" in Urdu.
 *
 * Look a value up with `label(L.voucherStatus, value)` from `lib/api/types`, which
 * falls back to the raw value rather than rendering blank.
 */
export function useLabels() {
  const L = useCatalog(labelsMessages);
  const unit = (value: string | null | undefined, quantity: number): string => {
    const key = (value ?? "unit") as keyof typeof L.unit;
    const map: Record<string, string> = quantity === 1 ? L.unit : L.unitPlural;
    return map[key] ?? value ?? map.unit;
  };
  return { ...L, unit };
}
