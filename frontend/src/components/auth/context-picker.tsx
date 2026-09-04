"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { Building2, School } from "lucide-react";
import { useState } from "react";

import { useTranslations } from "@/components/providers/i18n-provider";
import { authRequest } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { MembershipSummary } from "@/lib/api/types";

/**
 * Choose which membership to act as (spec §4.3D/E).
 *
 * Shown in two places: straight after a login that returned `select_required`, and
 * from the header switcher mid-session. Both call `/api/auth/context`, which
 * re-issues the token pair scoped to the chosen membership.
 *
 * Each option shows the ORGANIZATION and the SCHOOL, not just one of them. A person
 * can be a principal at two different clients' schools, and "Principal · Main
 * Campus" appearing twice with no way to tell them apart is exactly the confusion
 * this screen exists to remove.
 */
export function ContextPicker({
  memberships,
  redirectTo = "/dashboard",
  onSwitched,
}: {
  memberships: MembershipSummary[];
  /** Runtime path, so it is cast at the push site; see the login form. */
  redirectTo?: string;
  onSwitched?: () => void;
}) {
  const { t } = useTranslations();
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function select(membershipId: string) {
    setBusy(membershipId);
    setError(null);
    try {
      await authRequest("/context", { membership_id: membershipId });
      onSwitched?.();
      // Push before refresh so the shared app layout (sidebar) re-renders for the
      // new membership; a refresh issued before the push is superseded by it.
      router.push(redirectTo as Route);
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t.errors.generic);
      setBusy(null);
    }
  }

  return (
    <div className="grid gap-4">
      <div>
        <h2 className="font-medium">{t.auth.selectContext}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t.auth.selectContextHint}</p>
      </div>

      <ul className="grid gap-2">
        {memberships.map((membership) => {
          const Icon = membership.is_org_level ? Building2 : School;
          return (
            <li key={membership.membership_id}>
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => select(membership.membership_id)}
                className="flex w-full items-center gap-3 rounded-lg border border-border bg-card p-3 text-start transition-colors hover:border-primary hover:bg-accent disabled:opacity-60"
              >
                <span className="grid size-9 shrink-0 place-items-center rounded-md bg-accent text-accent-foreground">
                  <Icon className="size-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {membership.school_name ?? membership.organization_name}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {membership.role_name}
                    {/* The organization is shown alongside the school so two
                        identically-named campuses at different clients are
                        distinguishable. */}
                    {membership.school_name ? ` · ${membership.organization_name}` : " · Organization"}
                  </span>
                </span>
                {busy === membership.membership_id ? (
                  <span className="text-xs text-muted-foreground">{t.common.loading}</span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>

      {error ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
