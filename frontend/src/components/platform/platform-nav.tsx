"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Building2, FileClock, LayoutDashboard, Layers } from "lucide-react";

import { cn } from "@/lib/utils";

const NAV = [
  { href: "/platform" as Route, label: "Dashboard", icon: LayoutDashboard, exact: true },
  { href: "/platform/organizations" as Route, label: "Organizations", icon: Building2, exact: false },
  { href: "/platform/plans" as Route, label: "Plans", icon: Layers, exact: false },
  { href: "/platform/audit" as Route, label: "Audit", icon: FileClock, exact: false },
] as const;

/**
 * Console navigation. A client component only so the current section can be marked;
 * the chrome around it stays a server component.
 *
 * `variant="bar"` is the desktop header row; `variant="tabs"` is the scrollable strip
 * shown under the header on narrow screens, where the bar does not fit.
 */
export function PlatformNav({ variant }: { variant: "bar" | "tabs" }) {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Console"
      className={cn(
        "items-center gap-1 text-sm",
        variant === "bar" ? "hidden sm:flex" : "flex overflow-x-auto px-4 pb-2 sm:hidden",
      )}
    >
      {NAV.map(({ href, label, icon: Icon, exact }) => {
        const active = exact ? pathname === href : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 transition-colors",
              active
                ? "bg-slate-800 text-slate-50"
                : "text-slate-300 hover:bg-slate-800 hover:text-slate-50",
            )}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
