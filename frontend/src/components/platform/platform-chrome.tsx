import Link from "next/link";
import { LogOut } from "lucide-react";

import { PlatformNav } from "@/components/platform/platform-nav";
import { PlatformSignOut } from "@/components/platform/platform-sign-out";

/**
 * Chrome for the authenticated operator console.
 *
 * =============================================================================
 * DELIBERATELY LOOKS NOTHING LIKE THE TENANT APP
 * =============================================================================
 *   Spec §9 keeps the two surfaces apart at the session and token level. The visual
 *   separation is the human half of the same requirement.
 *
 *   An operator with a customer's data on screen must never be in any doubt about
 *   which hat they are wearing — a console that looks identical to the tenant app is
 *   how someone edits the wrong organization while believing they are in their own.
 *   Hence the dark chrome and the explicit "Operator console" label.
 */
export function PlatformChrome({
  children,
  adminName,
}: {
  children: React.ReactNode;
  adminName: string;
}) {
  return (
    <div className="min-h-svh bg-background">
      <header className="bg-slate-950 text-slate-100">
        <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-6 px-4 sm:px-6">
          <Link href="/platform" className="flex shrink-0 items-center gap-2 font-semibold">
            <span className="grid size-6 place-items-center rounded bg-slate-100 text-xs font-bold text-slate-950">
              E
            </span>
            Operator console
          </Link>

          <PlatformNav variant="bar" />

          <div className="ms-auto flex items-center gap-3 text-sm">
            <span className="hidden text-slate-400 sm:inline">{adminName}</span>
            <PlatformSignOut>
              <LogOut className="size-4" aria-hidden />
              <span className="sr-only">Sign out</span>
            </PlatformSignOut>
          </div>
        </div>
        <PlatformNav variant="tabs" />
      </header>

      <main id="main" className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6">
        {children}
      </main>
    </div>
  );
}
