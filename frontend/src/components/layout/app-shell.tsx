"use client";

import { Button as HeroButton, Drawer, useOverlayState } from "@heroui/react";
import { Menu } from "lucide-react";

import { OrganizationBanner } from "@/components/layout/organization-banner";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { UserMenu } from "@/components/layout/user-menu";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { LogoMark } from "@/components/marketing/logo";
import { GlobalSearch } from "@/components/search/global-search";
import { useRequiredSession } from "@/components/providers/session-provider";
import { SchoolLogo } from "@/components/ui/school-logo";
import type { SchoolRead } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * The authenticated app frame: sidebar, header, content.
 *
 * The sidebar is a permanent column from `lg` up and an overlay below it. A school
 * administrator on a phone in a corridor is a real user of this product, so the
 * small-screen path is not an afterthought — but the primary target is a desk, where
 * a persistent nav beats a hamburger.
 *
 * It is a black band (`panel-night`), like the public site's header, so the
 * product reads as one thing from the home page to the register. Below `lg` the
 * same nav slides in as HeroUI's drawer.
 */
export function AppShell({
  children,
  schools = [],
  activeSchoolId = null,
  activeSchool = null,
  activeSchoolName = null,
  logoUrl = null,
}: {
  children: React.ReactNode;
  /** The organization's campuses. Empty for a school-scoped member — see the layout. */
  schools?: SchoolRead[];
  activeSchoolId?: string | null;
  /** The open branch in full — the header shows its address, not just its name. */
  activeSchool?: SchoolRead | null;
  /** The branch whose modules the sidebar should open, or null. See the layout. */
  activeSchoolName?: string | null;
  /** The open campus's logo, already falling back to the organization's. */
  logoUrl?: string | null;
}) {
  const user = useRequiredSession();
  const mobileNav = useOverlayState();
  const brandName = activeSchoolName ?? user.organization_name ?? null;

  return (
    <div className="flex min-h-svh">
      {/* Desktop sidebar. `border-e` (inline-end), not `border-r`: under RTL the
          divider belongs on the other side, and a physical border would sit
          against the content instead of beside the nav. */}
      <aside className="panel-night hidden w-64 shrink-0 border-e border-sidebar-border bg-sidebar text-foreground lg:block">
        <div className="sticky top-0 flex h-svh flex-col">
          <Brand logoUrl={logoUrl} name={brandName} />
          <SidebarNav activeSchoolName={activeSchoolName} />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-card/80 px-4 backdrop-blur-xl backdrop-saturate-150 sm:px-6">
          {/* Mobile navigation: HeroUI's drawer, which brings the backdrop fade,
              the slide on its fluid curve, focus trapping and Escape. */}
          <Drawer state={mobileNav}>
            <HeroButton
              isIconOnly
              variant="ghost"
              size="sm"
              aria-label="Open navigation"
              className="lg:hidden"
            >
              <Menu className="size-4" aria-hidden />
            </HeroButton>
            <Drawer.Backdrop variant="blur">
              <Drawer.Content placement="left" className="lg:hidden">
                <Drawer.Dialog
                  aria-label="Navigation"
                  className="panel-night w-72 max-w-[85vw] bg-sidebar p-0 text-foreground sm:w-72"
                >
                  <Brand logoUrl={logoUrl} name={brandName} />
                  <Drawer.CloseTrigger aria-label="Close navigation" />
                  <SidebarNav activeSchoolName={activeSchoolName} onNavigate={mobileNav.close} />
                </Drawer.Dialog>
              </Drawer.Content>
            </Drawer.Backdrop>
          </Drawer>

          {/* Where you are, as a plain label rather than the dropdown this used to
              be — both switchers moved into the account menu.

              With a branch open the CAMPUS is the headline and its address sits
              underneath: several campuses of one group share a name stem, and
              "Cambridge Int Multan" versus "Cambridge Int Faisalabad" is a glance
              apart until you can see the street. The organization keeps a line only
              when there is no branch open and nothing to disambiguate. */}
          <div className="flex min-w-0 items-center gap-2">
            <SchoolLogo src={logoUrl} name={brandName} />
            {activeSchoolName ? (
              <>
                <div className="min-w-0 leading-tight">
                  <p className="truncate text-sm font-medium">{activeSchoolName}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {campusLocation(activeSchool) ?? user.organization_name}
                  </p>
                </div>
              </>
            ) : (
              <p className="truncate text-sm font-medium">
                {user.organization_name ?? "—"}
              </p>
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
        <OrganizationBanner
          status={user.organization_status}
          trialExpired={user.trial_expired ?? false}
          scheduledDeletionAt={user.scheduled_deletion_at ?? null}
        />

        <main id="main" className={cn("min-w-0 flex-1 px-4 py-6 sm:px-6 sm:py-8")}>
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

/**
 * The sidebar's masthead. A school that has a logo (its own, or its
 * organization's) sees its own brand here; SchoolYar's mark — the same one the
 * public site wears — is only the fallback for one that has not uploaded
 * anything yet.
 */
function Brand({ logoUrl, name }: { logoUrl: string | null; name: string | null }) {
  if (logoUrl) {
    return (
      <div className="flex h-16 min-w-0 shrink-0 items-center gap-2.5 px-5 pe-12 font-semibold tracking-tight lg:pe-5">
        <SchoolLogo src={logoUrl} name={name} className="bg-white p-0.5" />
        <span className="truncate">{name ?? "SchoolYar"}</span>
      </div>
    );
  }
  return (
    <div className="flex h-16 shrink-0 items-center gap-2.5 px-5 text-[1.05rem] font-bold tracking-[-0.02em]">
      <LogoMark className="size-7" />
      SchoolYar
    </div>
  );
}
