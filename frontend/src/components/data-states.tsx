"use client";

import { AlertTriangle, Inbox, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

/**
 * Skeleton rows sized to the column count, so the layout does not jump.
 *
 * RETURNS BARE `<tr>` ELEMENTS, so it belongs INSIDE a `<TableBody>` and nowhere
 * else. Dropped into a card or a plain div it produces `<tr>` under `<div>`, which
 * React reports as a hydration error and the browser silently unwraps — the rows
 * render, so it looks fine and is broken.
 *
 * When the table itself has not been rendered yet — the usual card-level "still
 * loading" state, where the header row is inside the same branch as the data —
 * reach for {@link TableCardSkeleton} instead. That is the shape this used to be
 * misused as.
 */
export function TableSkeleton({ columns, rows = 6 }: { columns: number; rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <TableRow key={rowIndex} aria-hidden>
          {Array.from({ length: columns }).map((__, colIndex) => (
            <TableCell key={colIndex}>
              <Skeleton className="h-4 w-full max-w-32" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

/**
 * The same skeleton rows, carrying their own table.
 *
 * For the common case where a card renders EITHER the loading state OR the whole
 * table — there is no `<TableBody>` to put rows into yet, so the rows have to bring
 * one. Sized to the column count for the same reason: the real table drops into the
 * same space without the card resizing under the reader.
 *
 * `aria-hidden`, because a table of empty cells announced to a screen reader is
 * worse than silence. The surrounding card is what says "loading".
 */
export function TableCardSkeleton({ columns, rows = 6 }: { columns: number; rows?: number }) {
  return (
    <Table aria-hidden>
      <TableBody>
        <TableSkeleton columns={columns} rows={rows} />
      </TableBody>
    </Table>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon: Icon = Inbox,
  className,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 px-6 py-14 text-center", className)}>
      <div className="rounded-full bg-muted p-3">
        <Icon className="size-5 text-muted-foreground" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-semibold">{title}</p>
        {description ? (
          <p className="mx-auto max-w-sm text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

/**
 * Error panel.
 *
 * A 403 is shown as a permissions message rather than a retry button — retrying
 * a forbidden request just fails again, which reads as a broken app.
 */
export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const forbidden = error instanceof ApiError && error.isForbidden;
  const requestId = error instanceof ApiError ? error.instance : undefined;

  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 px-6 py-14 text-center", className)}>
      <div className="rounded-full bg-destructive/10 p-3">
        <AlertTriangle className="size-5 text-destructive" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-semibold">
          {forbidden ? "You don't have access to this" : "Couldn't load this"}
        </p>
        <p className="mx-auto max-w-sm text-sm text-muted-foreground">{errorMessage(error)}</p>
        {requestId ? (
          <p className="text-xs text-muted-foreground/70">Request ID: {requestId}</p>
        ) : null}
      </div>
      {onRetry && !forbidden ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

export function PageSpinner() {
  return (
    <div className="flex items-center justify-center py-20">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
      <span className="sr-only">Loading</span>
    </div>
  );
}
