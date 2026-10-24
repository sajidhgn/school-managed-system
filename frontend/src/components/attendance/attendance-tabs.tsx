"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CalendarCheck, ChartColumn, Users } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The three attendance screens, one tab strip.
 *
 * The sidebar has ONE "Attendance" entry, and its prefix match keeps it lit on every
 * page under `/attendance` — so these live here rather than as three sidebar items
 * that would all be highlighted at once. Each answers a different question:
 *
 *   Registers  who has marked today, and marking itself
 *   Classes    which classes are slipping, and who is at risk
 *   Students   every child: today, this month, last month, the year
 */
const TABS: { href: Route; label: string; Icon: typeof Users }[] = [
  { href: "/attendance", label: "Registers", Icon: CalendarCheck },
  { href: "/attendance/analytics", label: "Classes", Icon: ChartColumn },
  { href: "/attendance/students", label: "Students", Icon: Users },
];

export function AttendanceTabs({ className }: { className?: string }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Attendance" className={cn("-mx-1 overflow-x-auto px-1", className)}>
      <ul className="inline-flex gap-1 rounded-lg border border-border bg-muted/40 p-1">
        {TABS.map(({ href, label, Icon }) => {
          const active = pathname === href;
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-sm transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  active
                    ? "bg-card font-medium text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
