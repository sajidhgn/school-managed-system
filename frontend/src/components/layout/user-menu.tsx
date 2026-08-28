"use client";

import { Building2, Check, LogOut, Monitor, Moon, School, Settings, Sun } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useState } from "react";

import { useTranslations } from "@/components/providers/i18n-provider";
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
import type { SchoolRead } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/** Initials for the avatar. Two letters max — three starts to look like a word. */
function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

/**
 * Account menu: who you are, where you are, and how to change either.
 *
 * =============================================================================
 * TWO KINDS OF MOVE, AND THEY ARE NOT THE SAME OPERATION
 * =============================================================================
 *   CAMPUS (`POST /auth/school`) — mints nothing. The principal is org-level and
 *   already administers every campus, so choosing one narrows what the
 *   school-scoped pages DISPLAY and touches nothing else.
 *
 *   MEMBERSHIP (`POST /auth/context`) — mints a new access token. The permission
 *   set, the school scope and the RLS organization all change with it; the server
 *   genuinely starts answering as that person in that place. This is how someone
 *   who works at two organizations moves between them.
 *
 *   Both then `router.refresh()` rather than setting client state: the source of
 *   truth is an httpOnly cookie, and a client that "remembered" something different
 *   would show one school's chrome around another school's data.
 *
 * Both used to be a dropdown of their own in the header. They live here because for
 * most people each has exactly one option, and a permanent control in the header
 * advertising a choice nobody has is noise.
 */
export function UserMenu({
  schools = [],
  activeSchoolId = null,
}: {
  /** The organization's campuses. Only populated for an org-level user. */
  schools?: SchoolRead[];
  activeSchoolId?: string | null;
}) {
  const user = useRequiredSession();
  const { t } = useTranslations();
  const { theme, setTheme } = useTheme();
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);
  const [busy, setBusy] = useState(false);

  const activeSchool = schools.find((s) => s.id === activeSchoolId) ?? null;

  async function viewSchool(schoolId: string) {
    if (schoolId === activeSchoolId) return;
    setBusy(true);
    try {
      await authRequest("/school", { school_id: schoolId });
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  async function switchTo(membershipId: string) {
    if (membershipId === user.active_membership_id) return;
    setBusy(true);
    try {
      await authRequest("/context", { membership_id: membershipId });
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  async function signOut(everywhere: boolean) {
    setSigningOut(true);
    await fetch(`/api/auth/logout${everywhere ? "?all=true" : ""}`, { method: "POST" });
    // A full navigation, not `router.push`. Sign-out must leave no cached RSC
    // payload holding the previous user's data — which matters on the shared
    // machines common in a staff room.
    window.location.href = "/login";
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="grid size-9 place-items-center rounded-full bg-accent text-sm font-medium text-accent-foreground transition-colors hover:bg-accent/80"
          aria-label="Account menu"
        >
          {initials(user.full_name)}
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="font-normal">
          <p className="text-sm font-medium">{user.full_name}</p>
          <p className="truncate text-xs text-muted-foreground">{user.email}</p>
          {user.role_code ? (
            <p className="mt-1 text-xs text-muted-foreground">
              {/* The campus, when one is selected — NOT `organization_name`. An
                  org-level principal has no `school_name` on their membership, so
                  falling back to the organization here would leave the one thing
                  they actually chose invisible everywhere in the chrome. */}
              {user.role_code} ·{" "}
              {user.school_name ?? activeSchool?.name ?? user.organization_name}
            </p>
          ) : null}
        </DropdownMenuLabel>

        {schools.length > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
              {t.nav.schools}
            </DropdownMenuLabel>
            {schools.map((school) => (
              <DropdownMenuItem
                key={school.id}
                onSelect={() => viewSchool(school.id)}
                disabled={busy}
                className="gap-2"
              >
                <School className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1 truncate text-sm">{school.name}</span>
                <Check
                  className={cn(
                    "size-4 shrink-0",
                    school.id === activeSchoolId ? "opacity-100" : "opacity-0",
                  )}
                  aria-hidden
                />
              </DropdownMenuItem>
            ))}
          </>
        ) : null}

        {user.memberships.length > 1 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
              Switch context
            </DropdownMenuLabel>
            {user.memberships.map((membership) => (
              <DropdownMenuItem
                key={membership.membership_id}
                onSelect={() => switchTo(membership.membership_id)}
                disabled={busy}
                className="gap-2"
              >
                {membership.is_org_level ? (
                  <Building2 className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                ) : (
                  <School className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">
                    {membership.school_name ?? membership.organization_name}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {membership.role_name}
                  </span>
                </span>
                <Check
                  className={cn(
                    "size-4 shrink-0",
                    membership.membership_id === user.active_membership_id
                      ? "opacity-100"
                      : "opacity-0",
                  )}
                  aria-hidden
                />
              </DropdownMenuItem>
            ))}
          </>
        ) : null}

        <DropdownMenuSeparator />

        <DropdownMenuItem asChild>
          <Link href="/settings" className="gap-2">
            <Settings className="size-4" aria-hidden />
            {t.nav.settings}
          </Link>
        </DropdownMenuItem>

        <DropdownMenuSeparator />

        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          Theme
        </DropdownMenuLabel>
        {(
          [
            ["light", Sun, "Light"],
            ["dark", Moon, "Dark"],
            ["system", Monitor, "System"],
          ] as const
        ).map(([value, Icon, labelText]) => (
          <DropdownMenuItem
            key={value}
            onSelect={() => setTheme(value)}
            className="gap-2"
            data-active={theme === value}
          >
            <Icon className="size-4" aria-hidden />
            {labelText}
          </DropdownMenuItem>
        ))}

        <DropdownMenuSeparator />

        <DropdownMenuItem
          onSelect={() => signOut(false)}
          disabled={signingOut}
          className="gap-2"
        >
          <LogOut className="size-4" aria-hidden />
          {t.common.signOut}
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => signOut(true)}
          disabled={signingOut}
          className="gap-2 text-muted-foreground"
        >
          {/* Offered alongside the ordinary sign-out because "I think someone else
              has my password" needs a one-click answer, and burying it in settings
              means nobody finds it at the moment they need it. */}
          <LogOut className="size-4" aria-hidden />
          Sign out on all devices
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
