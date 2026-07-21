"use client";

import { AlertTriangle, Inbox, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import { TableCell, TableRow } from "@/components/ui/table";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

/** Skeleton rows sized to the column count, so the layout does not jump. */
export function TableSkeleton({ columns, rows = 6 }: { columns: number; rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <TableRow key={rowIndex}>
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
