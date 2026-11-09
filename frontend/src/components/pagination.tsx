"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { fill } from "@/lib/i18n/format";
import { sharedMessages } from "@/lib/i18n/modules/shared";
import { useCatalog } from "@/lib/i18n/use-catalog";

import { Button } from "@/components/ui/button";
import type { PageMeta } from "@/lib/api/types";

/**
 * Pager driven by the backend's PageMeta.
 *
 * Uses `has_next`/`has_prev` from the server rather than deriving them from
 * page arithmetic — the server knows about concurrent inserts, the client
 * doesn't.
 */
export function Pagination({
  meta,
  onPageChange,
  disabled,
}: {
  meta: PageMeta;
  onPageChange: (page: number) => void;
  disabled?: boolean;
}) {
  const m = useCatalog(sharedMessages);
  if (meta.total === 0) return null;

  const first = (meta.page - 1) * meta.size + 1;
  const last = Math.min(meta.page * meta.size, meta.total);

  return (
    <div className="flex flex-col gap-3 border-t border-border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-xs text-muted-foreground">
        {fill(m.showing, { first, last, total: meta.total })}
      </p>

      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!meta.has_prev || disabled}
          onClick={() => onPageChange(meta.page - 1)}
        >
          <ChevronLeft className="rtl:rotate-180" />
          {m.previous}
        </Button>
        <span className="px-1 text-xs text-muted-foreground" aria-live="polite">
          {fill(m.pageOf, { page: meta.page, pages: meta.pages })}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={!meta.has_next || disabled}
          onClick={() => onPageChange(meta.page + 1)}
        >
          {m.next}
          <ChevronRight className="rtl:rotate-180" />
        </Button>
      </div>
    </div>
  );
}
