"use client";

import { Menu, X } from "lucide-react";
import { useState } from "react";

import { ContextSwitcher } from "@/components/layout/context-switcher";
import { OrganizationBanner } from "@/components/layout/organization-banner";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { UserMenu } from "@/components/layout/user-menu";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { useRequiredSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The authenticated app frame: sidebar, header, content.
 *
 * The sidebar is a permanent column from `lg` up and an overlay below it. A school
 * administrator on a phone in a corridor is a real user of this product, so the
 * small-screen path is not an afterthought — but the primary target is a desk, where
 * a persistent nav beats a hamburger.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
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
          <SidebarNav />
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
            <SidebarNav onNavigate={() => setMobileOpen(false)} />
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

          <ContextSwitcher />

          <div className="ms-auto flex items-center gap-2">
            <LocaleSwitcher />
            <UserMenu />
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
