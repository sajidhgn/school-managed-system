import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/* `rounded-control` is the theme's own radius (globals.css). Without it on the
   scale, `cn("rounded-control", "rounded-md")` keeps both and the stylesheet
   order picks the winner instead of the caller. */
const twMerge = extendTailwindMerge({ extend: { theme: { borderRadius: ["control"] } } });

/** Merge Tailwind classes, letting later conflicting utilities win. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Wrap a left-to-right run (a date, "14 Mar 2015") in a Unicode LTR isolate.
 *
 * In an Urdu (right-to-left) sentence the bidi algorithm otherwise splits
 * "14 Mar 2015" around the month and shows "Mar 2015 14". The isolate marks are
 * invisible, and make the run read as one unit in either direction.
 */
function isolateLtr(text: string): string {
  return `\u2066${text}\u2069`;
}

/** Format an ISO date/datetime for display. Returns "—" for null. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return isolateLtr(
    new Intl.DateTimeFormat("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }).format(date),
  );
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return isolateLtr(
    new Intl.DateTimeFormat("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date),
  );
}

/** Initials for an avatar fallback, e.g. "Aisha Khan" → "AK". */
export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

/** `null` for empty strings — the backend distinguishes "" from absent. */
export function emptyToNull<T extends Record<string, unknown>>(values: T): T {
  const out = { ...values };
  for (const key of Object.keys(out) as (keyof T)[]) {
    if (out[key] === "") out[key] = null as T[keyof T];
  }
  return out;
}
