"use client";

import { Building2, Menu, School, X } from "lucide-react";
import { useState } from "react";

import { OrganizationBanner } from "@/components/layout/organization-banner";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { UserMenu } from "@/components/layout/user-menu";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { GlobalSearch } from "@/components/search/global-search";
import { useRequiredSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import type { SchoolRead } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * The authenticated app frame: sidebar, header, content.
 *
 * The sidebar is a permanent column from `lg` up and an overlay below it. A school
 * administrator on a phone in a corridor is a real user of this product, so the
 * small-screen path is not an afterthought — but the primary target is a desk, where
 * a persistent nav beats a hamburger.
 */
export function AppShell({
  children,
  schools = [],
  activeSchoolId = null,
  activeSchool = null,
  activeSchoolName = null,
}: {
  children: React.ReactNode;
  /** The organization's campuses. Empty for a school-scoped member — see the layout. */
  schools?: SchoolRead[];
  activeSchoolId?: string | null;
  /** The open branch in full — the header shows its address, not just its name. */
  activeSchool?: SchoolRead | null;
  /** The branch whose modules the sidebar should open, or null. See the layout. */
  activeSchoolName?: string | null;
}) {
  const user = useRequiredSession();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-svh">
      {/* Desktop sidebar. `border-e` (inline-end), not `border-r`: under RTL the
          divider belongs on the other side, and a physical border would sit
          against the content instead of beside the nav. */}
      <aside className="hidden w-64 shrink-0 border-e border-sidebar-border bg-sidebar lg:block">
        <div className="sticky top-0 flex h-svh flex-col">
          <Brand />
          <SidebarNav activeSchoolName={activeSchoolName} />
        </div>
      </aside>

      {/* Mobile drawer */}
      {mobileOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-black/40"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="absolute inset-y-0 start-0 flex w-64 flex-col border-e border-sidebar-border bg-sidebar">
            <div className="flex items-center">
              <Brand />
              <Button
                variant="ghost"
                size="icon"
                className="me-2 ms-auto"
                onClick={() => setMobileOpen(false)}
              >
                <X className="size-4" aria-hidden />
                <span className="sr-only">Close</span>
              </Button>
            </div>
            <SidebarNav activeSchoolName={activeSchoolName} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-background/90 px-4 backdrop-blur sm:px-6">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={() => setMobileOpen(true)}
          >
            <Menu className="size-4" aria-hidden />
            <span className="sr-only">Open navigation</span>
          </Button>

          {/* Where you are, as a plain label rather than the dropdown this used to
              be — both switchers moved into the account menu.

              With a branch open the CAMPUS is the headline and its address sits
              underneath: several campuses of one group share a name stem, and
              "Cambridge Int Multan" versus "Cambridge Int Faisalabad" is a glance
              apart until you can see the street. The organization keeps a line only
              when there is no branch open and nothing to disambiguate. */}
          <div className="flex min-w-0 items-center gap-2">
            {activeSchoolName ? (
              <>
                <School className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <div className="min-w-0 leading-tight">
                  <p className="truncate text-sm font-medium">{activeSchoolName}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {campusLocation(activeSchool) ?? user.organization_name}
                  </p>
                </div>
              </>
            ) : (
              <>
                <Building2 className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <p className="truncate text-sm font-medium">
                  {user.organization_name ?? "—"}
                </p>
              </>
            )}
          </div>

          <div className="ms-auto flex items-center gap-2">
            {/* Search sits in the header rather than the sidebar because it is the
                one control that is about EVERYWHERE, not about the section you are
                in — and because ⌘K has to be reachable from every page, including
                the ones with no sidebar on a phone. */}
            <GlobalSearch />
            <LocaleSwitcher />
            <UserMenu schools={schools} activeSchoolId={activeSchoolId} />
          </div>
        </header>

        {/* Subscription state banners: over-limit, past-due, suspended. Placed above
            the content rather than on the billing page, because the user hits the
            consequence (a blocked create) somewhere else entirely and needs the
            explanation where they are. */}
        <OrganizationBanner status={user.organization_status} />

        <main id="main" className={cn("flex-1 px-4 py-6 sm:px-6 sm:py-8")}>
          {children}
        </main>
      </div>
    </div>
  );
}

/**
 * The campus's address for the header's second line, or null.
 *
 * `address` already carries the city on every record the app writes ("12 Main
 * Boulevard, Lahore"), so appending `city` to it would read "…, Lahore, Lahore".
 * City alone is the fallback for a campus nobody has given a street to yet, and the
 * code is appended because two campuses in one city are told apart by it.
 */
function campusLocation(school: SchoolRead | null): string | null {
  if (!school) return null;
  const place = school.address?.trim() || school.city?.trim() || null;
  if (!place) return school.code ?? null;
  return school.code ? `${place} · ${school.code}` : place;
}

function Brand() {
  return (
    <div className="flex h-16 items-center gap-2 px-5 font-semibold tracking-tight">
      <span className="grid size-7 place-items-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">
        E
      </span>
      EduCloud
    </div>
  );
}
