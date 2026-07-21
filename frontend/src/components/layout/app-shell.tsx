"use client";

import * as React from "react";
import Link from "next/link";
import { Menu, School } from "lucide-react";

import { SidebarNav } from "@/components/layout/sidebar-nav";
import { UserMenu } from "@/components/layout/user-menu";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import type { SchoolRead, UserRead } from "@/lib/api/types";

/**
 * Dashboard chrome: persistent sidebar on desktop, dialog drawer on mobile.
 *
 * `user` and `school` are resolved on the server and passed down, so the shell
 * paints with the correct identity on first byte — no auth flash.
 */
export function AppShell({
  user,
  school,
  children,
}: {
  user: UserRead;
  school: SchoolRead | null;
  children: React.ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = React.useState(false);

  const brand = (
    <div className="flex items-center gap-2 px-4 py-4">
      <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <School className="size-4" />
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold leading-tight">
          {school?.name ?? "School Management"}
        </p>
        <p className="truncate text-xs text-muted-foreground">
          {school ? `@${school.slug}` : "Platform administration"}
        </p>
      </div>
    </div>
  );

  return (
    <div className="flex min-h-svh">
      {/* Desktop sidebar */}
      <aside className="hidden w-64 shrink-0 border-r border-sidebar-border bg-sidebar lg:block">
        <div className="sticky top-0">
          {brand}
          <SidebarNav role={user.role} />
        </div>
      </aside>

      {/* Mobile drawer */}
      <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
        <DialogContent className="left-0 top-0 h-svh max-w-72 translate-x-0 translate-y-0 rounded-none border-y-0 border-l-0 p-0">
          <DialogTitle className="sr-only">Navigation</DialogTitle>
          {brand}
          <SidebarNav role={user.role} onNavigate={() => setMobileOpen(false)} />
        </DialogContent>
      </Dialog>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-border bg-background/85 px-4 backdrop-blur">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="lg:hidden"
              onClick={() => setMobileOpen(true)}
              aria-label="Open navigation"
            >
              <Menu />
            </Button>
            <Link href="/dashboard" className="text-sm font-semibold lg:hidden">
              {school?.name ?? "School Management"}
            </Link>
          </div>

          <UserMenu user={user} />
        </header>

        <main id="main" className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
