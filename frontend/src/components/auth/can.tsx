"use client";

import type { ReactNode } from "react";

import { useSession } from "@/components/providers/session-provider";
import { can, canAny } from "@/lib/auth/permissions";

/**
 * Conditional rendering by permission (spec §9's `<Can permission="…">`).
 *
 *   <Can permission="member:invite">
 *     <Button>Invite staff</Button>
 *   </Can>
 *
 * UI HIDING IS COSMETIC ONLY. The server re-checks every action. This exists so the
 * interface tells the truth about what the user can do — not to keep anyone out.
 *
 * `fallback` is for the cases where silence would be confusing: an empty table with
 * no explanation reads as "there is no data" rather than "you cannot see this".
 * Prefer a short explanatory line over a blank region for whole sections; leave it
 * undefined for individual buttons, where absence is self-explanatory.
 */
export function Can({
  permission,
  anyOf,
  fallback = null,
  children,
}: {
  /** Every code must be held. */
  permission?: string | string[];
  /** At least one code must be held. Use for nav groups several permissions unlock. */
  anyOf?: string[];
  fallback?: ReactNode;
  children: ReactNode;
}) {
  const { user } = useSession();

  const required = permission === undefined ? [] : Array.isArray(permission) ? permission : [permission];
  const allowed =
    (required.length === 0 || can(user, ...required)) &&
    (anyOf === undefined || canAny(user, ...anyOf));

  return <>{allowed ? children : fallback}</>;
}
