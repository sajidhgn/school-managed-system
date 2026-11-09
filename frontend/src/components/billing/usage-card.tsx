import type { UsageItem, UsageResponse } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * Plan usage against limits.
 *
 * Shows the metered limits from `GET /org/usage`, which is readable by ANY member —
 * deliberately, so a teacher who hits a student limit can see why the create failed
 * rather than being told only "forbidden" and having to ask the principal.
 *
 * `allowed === -1` is the backend's sentinel for unlimited. It is rendered as the
 * word, never as a bar: a progress bar for an unbounded quantity has no meaningful
 * fill, and showing one at 0% suggests the opposite of what is true.
 */
export interface UsageCardStrings {
  /** Display name per usage key (`useLabels().usage`, or `labelsMessages` on the server). */
  labels: Record<string, string>;
  /** After the slash for an unbounded quantity: "12 / unlimited". */
  unlimited: string;
  /** Under an exhausted bar. */
  exhausted: string;
}

export function UsageCard({
  usage,
  strings,
}: {
  usage: UsageResponse;
  /** Passed in rather than hooked: this renders inside Server Components, which
   *  read the catalogs with `getTranslations()` / `getCatalog()` rather than a
   *  client context. */
  strings: UsageCardStrings;
}) {
  return (
    <div className="grid gap-4 rounded-xl border border-border bg-card p-5 sm:grid-cols-2">
      {usage.items.map((item) => (
        <UsageBar key={item.key} item={item} strings={strings} />
      ))}
    </div>
  );
}

function UsageBar({ item, strings }: { item: UsageItem; strings: UsageCardStrings }) {
  const label = strings.labels[item.key] ?? item.key;

  if (item.is_unlimited) {
    return (
      <div>
        <div className="flex items-baseline justify-between gap-3 text-sm">
          <span className="text-muted-foreground">{label}</span>
          <span className="font-medium tabular-nums">
            {item.current} <span className="text-muted-foreground">/ {strings.unlimited}</span>
          </span>
        </div>
        <div className="mt-2 h-1.5 rounded-full bg-muted" />
      </div>
    );
  }

  const pct = item.allowed > 0 ? Math.min(100, (item.current / item.allowed) * 100) : 0;
  // Amber before the wall, not at it. A principal who sees "23/25 staff" a week
  // before hiring can plan; one who discovers it at the 26th invitation cannot.
  const nearLimit = pct >= 80 && !item.is_exhausted;

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span
          className={cn(
            "font-medium tabular-nums",
            item.is_exhausted ? "text-destructive" : nearLimit ? "text-warning" : "",
          )}
        >
          {item.current} <span className="text-muted-foreground">/ {item.allowed}</span>
        </span>
      </div>
      <div
        className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={item.current}
        aria-valuemin={0}
        aria-valuemax={item.allowed}
        aria-label={label}
      >
        <div
          className={cn(
            "h-full rounded-full transition-all",
            item.is_exhausted ? "bg-destructive" : nearLimit ? "bg-warning" : "bg-primary",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      {item.is_exhausted ? (
        <p className="mt-1.5 text-xs text-destructive">
          {strings.exhausted}
        </p>
      ) : null}
    </div>
  );
}
