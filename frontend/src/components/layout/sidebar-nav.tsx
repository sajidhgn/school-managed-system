"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Building2,
  GraduationCap,
  LayoutDashboard,
  Layers,
  Settings,
  Users,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { can } from "@/lib/auth/permissions";
import type { UserRole } from "@/lib/api/types";

interface NavItem {
  /** `Route` (not `string`) so a typo'd or deleted page fails the build. */
  href: Route;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  visible: (role: UserRole) => boolean;
}

const NAV: NavItem[] = [
  {
    href: "/dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    visible: () => true,
  },
  {
    href: "/students",
    label: "Students",
    icon: Users,
    visible: can.viewRosters,
  },
  {
    href: "/classes",
    label: "Classes",
    icon: Layers,
    visible: can.viewRosters,
  },
  {
    href: "/admissions-queue",
    label: "Admissions",
    icon: GraduationCap,
    visible: can.manageSchoolData,
  },
  {
    href: "/schools",
    label: "Schools",
    icon: Building2,
    visible: can.manageTenants,
  },
  {
    href: "/settings",
    label: "Settings",
    icon: Settings,
    visible: () => true,
  },
];

export function SidebarNav({ role, onNavigate }: { role: UserRole; onNavigate?: () => void }) {
  const pathname = usePathname();
  const items = NAV.filter((item) => item.visible(role));

  return (
    <nav className="flex flex-col gap-0.5 p-3" aria-label="Main">
      {items.map(({ href, label, icon: Icon }) => {
        // `/students/abc` should keep "Students" active, but `/` must not
        // match everything.
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-sidebar-accent text-sidebar-accent-foreground"
                : "text-sidebar-foreground hover:bg-sidebar-accent/60",
            )}
          >
            <Icon className="size-4 shrink-0" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
