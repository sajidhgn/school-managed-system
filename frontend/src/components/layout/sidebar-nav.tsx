"use client";

import {
  BookOpen,
  Building2,
  CalendarCheck,
  CalendarRange,
  ClipboardList,
  CreditCard,
  GraduationCap,
  LayoutDashboard,
  Layers,
  MessageCircle,
  NotebookPen,
  Receipt,
  ScrollText,
  Settings,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useTranslations } from "@/components/providers/i18n-provider";
import { useRequiredSession } from "@/components/providers/session-provider";
import { PERMISSIONS } from "@/lib/api/types";
import { canAny } from "@/lib/auth/permissions";
import { cn } from "@/lib/utils";

/**
 * Permission-driven navigation.
 *
 * Every item declares the permissions that make it meaningful, and a section with
 * nothing visible disappears entirely rather than rendering an empty heading.
 *
 * =============================================================================
 * THIS IS NOT ACCESS CONTROL
 * =============================================================================
 *   Hiding a link does not protect the page behind it — the route still exists, and
 *   typing the URL still reaches it. The server's `require(...)` dependency is what
 *   refuses the request.
 *
 *   What this DOES buy is an interface that tells the truth. A teacher who cannot
 *   manage billing should not spend time wondering why the billing page rejects
 *   them; it simply is not part of their product.
 *
 * `anyOf` semantics, not `all`: the People section is worth showing to someone who
 * can read members OR manage roles OR see invitations. Requiring all three would
 * hide it from almost everyone who has a legitimate use for part of it.
 */

interface NavItem {
  // `Route`, not `string`: `typedRoutes` then verifies every nav destination
  // against the real app/ tree at build time, so a renamed page cannot leave a
  // dead link in the sidebar.
  href: Route;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  anyOf?: string[];
  /** Hidden when there is no campus for the page to act on. */
  requiresSchool?: boolean;
}

export function SidebarNav({
  activeSchoolName = null,
  onNavigate,
}: {
  /**
   * The branch whose modules are open, or null when none is.
   *
   * =========================================================================
   * THE CAMPUS MODULES BELONG TO A BRANCH, NOT TO THE APP
   * =========================================================================
   *   Members, Roles, Invitations, Students, Classes and Audit all act on ONE
   *   campus. Showing them permanently would mean six links whose meaning depends
   *   on a selection made elsewhere and displayed nowhere — you would click
   *   "Members" and get whichever branch the app last happened to be pointed at.
   *
   *   So they are grouped under the branch's NAME and appear only once a branch is
   *   open. Opening a different branch moves the whole group to it, which is what
   *   makes the sidebar readable as "here is where I am, here is what I can do
   *   here".
   *
   *   NOT derived from `user.school_id`: only a school-SCOPED member carries a
   *   school on their session. The principal is org-level and never does, however
   *   many campuses they run — testing that hid all six from the one person who
   *   administers all of them.
   */
  activeSchoolName?: string | null;
  onNavigate?: () => void;
}) {
  const { t } = useTranslations();
  const user = useRequiredSession();
  const pathname = usePathname();

  const sections: { heading?: string; items: NavItem[] }[] = [
    {
      items: [
        { href: "/dashboard", label: t.nav.dashboard, icon: LayoutDashboard },
        {
          href: "/schools",
          label: t.nav.schools,
          icon: Building2,
          anyOf: [PERMISSIONS.schoolRead],
        },
      ],
    },
    {
      // The open branch, named. Everything under it acts on that campus and nothing
      // else, which is why they are one group rather than scattered through the nav.
      heading: activeSchoolName ?? undefined,
      items: [
        {
          href: "/members",
          label: t.nav.members,
          icon: Users,
          anyOf: [PERMISSIONS.memberRead],
          requiresSchool: true,
        },
        {
          href: "/roles",
          label: t.nav.roles,
          icon: ShieldCheck,
          anyOf: [PERMISSIONS.roleRead],
          requiresSchool: true,
        },
        {
          href: "/students",
          label: t.nav.students,
          icon: GraduationCap,
          anyOf: [PERMISSIONS.studentRead],
          requiresSchool: true,
        },
        {
          href: "/classes",
          label: t.nav.classes,
          icon: Layers,
          anyOf: [PERMISSIONS.classRead],
          requiresSchool: true,
        },
        {
          href: "/attendance",
          label: t.nav.attendance,
          icon: CalendarCheck,
          // `attendance:read` alone, not `attendance:mark`: a head of year who
          // chases missing registers without ever marking one still needs the board.
          anyOf: [PERMISSIONS.attendanceRead],
          requiresSchool: true,
        },
        {
          href: "/diary",
          label: t.nav.diary,
          icon: NotebookPen,
          anyOf: [PERMISSIONS.diaryRead],
          requiresSchool: true,
        },
        {
          href: "/academic-years",
          label: t.nav.calendar,
          icon: CalendarRange,
          anyOf: [PERMISSIONS.calendarRead],
          requiresSchool: true,
        },
        {
          href: "/subjects",
          label: t.nav.subjects,
          icon: BookOpen,
          anyOf: [PERMISSIONS.subjectRead],
          requiresSchool: true,
        },
        {
          href: "/exams",
          label: t.nav.exams,
          icon: ClipboardList,
          // `grade:read` alone: a coordinator who reads result sheets without
          // ever entering a mark still needs the schedule.
          anyOf: [PERMISSIONS.gradeRead],
          requiresSchool: true,
        },
        {
          href: "/fees",
          label: t.nav.fees,
          icon: Receipt,
          anyOf: [PERMISSIONS.feeRead],
          requiresSchool: true,
        },
        {
          href: "/whatsapp",
          label: t.nav.whatsapp,
          icon: MessageCircle,
          anyOf: [PERMISSIONS.whatsappRead],
          requiresSchool: true,
        },
        {
          href: "/audit",
          label: t.nav.audit,
          icon: ScrollText,
          anyOf: [PERMISSIONS.auditRead],
          requiresSchool: true,
        },
      ],
    },
    {
      heading: "Organization",
      items: [
        {
          href: "/billing",
          label: t.nav.billing,
          icon: CreditCard,
          anyOf: [PERMISSIONS.billingRead, PERMISSIONS.billingManage],
        },
        { href: "/settings", label: t.nav.settings, icon: Settings },
      ],
    },
  ];

  const visible = (item: NavItem) => {
    if (item.requiresSchool && !activeSchoolName) return false;
    if (!item.anyOf) return true;
    return canAny(user, ...item.anyOf);
  };

  return (
    <nav className="flex-1 overflow-y-auto px-3 pb-6" aria-label="Main">
      {sections.map((section, index) => {
        const items = section.items.filter(visible);
        if (items.length === 0) return null;

        return (
          <div key={index} className="mb-5">
            {section.heading ? (
              <h2 className="truncate px-2 pb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {section.heading}
              </h2>
            ) : null}
            <ul className="grid gap-0.5">
              {items.map(({ href, label, icon: Icon }) => {
                // Prefix match so `/students/abc` keeps "Students" highlighted, but
                // exact for `/dashboard`, which would otherwise match everything.
                const active =
                  href === "/dashboard"
                    ? pathname === href
                    : pathname === href || pathname.startsWith(`${href}/`);

                return (
                  <li key={href}>
                    <Link
                      href={href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors",
                        active
                          ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                          : "text-sidebar-foreground hover:bg-sidebar-accent/60",
                      )}
                    >
                      <Icon className="size-4 shrink-0" aria-hidden />
                      {label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}
