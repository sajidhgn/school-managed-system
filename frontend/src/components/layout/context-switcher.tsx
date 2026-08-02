"use client";

import { Building2, Check, ChevronsUpDown, School } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useRequiredSession } from "@/components/providers/session-provider";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { authRequest } from "@/lib/api/client";
import { cn } from "@/lib/utils";

/**
 * The school / organization switcher in the header (spec §9).
 *
 * Shows the ACTIVE context and lets the user move between the memberships they hold.
 * A person can be a principal at one campus and an accountant at another, or an
 * owner with both an org-level view and a school view — and which one they are
 * currently acting as changes what every page shows.
 *
 * =============================================================================
 * SWITCHING RE-ISSUES THE TOKEN, IT DOES NOT FILTER THE UI
 * =============================================================================
 *   `POST /auth/context` mints a new access token scoped to the chosen membership.
 *   The permission set, the school scope and the RLS organization all change with
 *   it — the server genuinely starts answering as that person in that place.
 *
 *   That is why this calls a route handler and then `router.refresh()` rather than
 *   setting client state: the source of truth is an httpOnly cookie, and a client
 *   that "remembered" a different context than the cookie carries would show one
 *   school's chrome around another school's data.
 *
 * With a single membership there is nothing to switch to, so the control renders as
 * a plain label — a disabled dropdown with one option is noise.
 */
export function ContextSwitcher() {
  const user = useRequiredSession();
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  const active = user.memberships.find((m) => m.membership_id === user.active_membership_id);
  const Icon = active?.is_org_level ? Building2 : School;

  const primaryLabel = active?.school_name ?? user.organization_name ?? "—";
  const secondaryLabel = active?.is_org_level
    ? user.organization_name ?? "Organization"
    : active?.role_name ?? "";

  if (user.memberships.length <= 1) {
    return (
      <div className="flex min-w-0 items-center gap-2">
        <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{primaryLabel}</p>
          {secondaryLabel ? (
            <p className="truncate text-xs text-muted-foreground">{secondaryLabel}</p>
          ) : null}
        </div>
      </div>
    );
  }

  async function switchTo(membershipId: string) {
    if (membershipId === user.active_membership_id) return;
    setBusy(true);
    try {
      await authRequest("/context", { membership_id: membershipId });
      // Refresh rather than push: the user stays where they are, but every server
      // component re-renders under the new context. Navigating to /dashboard would
      // lose their place for no reason.
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={busy}
          className="flex min-w-0 max-w-[16rem] items-center gap-2 rounded-md px-2 py-1.5 text-start transition-colors hover:bg-accent disabled:opacity-60"
        >
          <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{primaryLabel}</span>
            {secondaryLabel ? (
              <span className="block truncate text-xs text-muted-foreground">
                {secondaryLabel}
              </span>
            ) : null}
          </span>
          <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="w-72">
        <DropdownMenuLabel>Switch context</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {user.memberships.map((membership) => {
          const isActive = membership.membership_id === user.active_membership_id;
          const RowIcon = membership.is_org_level ? Building2 : School;
          return (
            <DropdownMenuItem
              key={membership.membership_id}
              onSelect={() => switchTo(membership.membership_id)}
              className="gap-2"
            >
              <RowIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm">
                  {membership.school_name ?? membership.organization_name}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {membership.role_name}
                  {membership.school_name ? ` · ${membership.organization_name}` : ""}
                </span>
              </span>
              <Check
                className={cn("size-4 shrink-0", isActive ? "opacity-100" : "opacity-0")}
                aria-hidden
              />
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
