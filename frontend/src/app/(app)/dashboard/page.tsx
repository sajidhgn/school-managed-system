import type { Metadata, Route } from "next";
import Link from "next/link";
import { Building2, Mail, Users } from "lucide-react";

import { Can } from "@/components/auth/can";
import { UsageCard } from "@/components/billing/usage-card";
import { AnalyticsBoard } from "@/components/dashboard/analytics";
import { Button } from "@/components/ui/button";
import { serverGet } from "@/lib/api/server";
import {
  PERMISSIONS,
  type DashboardAnalytics,
  type InvitationRead,
  type MemberRead,
  type Page,
  type SchoolRead,
  type UsageResponse,
} from "@/lib/api/types";
import { hasPermission, requireUser } from "@/lib/auth/session";
import { getTranslations } from "@/lib/i18n/server";

export const metadata: Metadata = { title: "Dashboard" };

/**
 * The landing screen after sign-in.
 *
 * Built from what the CURRENT context can see. The org-level principal gets the
 * organization's shape — schools, plan usage; a school-scoped member gets their
 * campus — staff, pending invitations. Rendering the same cards to both and letting
 * half of them 403 would be worse than showing fewer, truthful ones.
 *
 * Every fetch degrades to an empty value rather than failing the page. A dashboard
 * that goes blank because one endpoint is slow is the fastest way to make a working
 * system look broken.
 */
export default async function DashboardPage() {
  const [user, t] = await Promise.all([requireUser(), getTranslations()]);
  const schoolId = user.school_id;

  const [schools, usage, members, invitations, analytics] = await Promise.all([
    hasPermission(user, PERMISSIONS.schoolRead)
      ? serverGet<SchoolRead[]>("/schools", [])
      : Promise.resolve<SchoolRead[]>([]),
    serverGet<UsageResponse | null>("/org/usage", null),
    // Only the total is displayed, so ask for the smallest page the endpoint
    // allows and read the count from its metadata.
    schoolId && hasPermission(user, PERMISSIONS.memberRead)
      ? serverGet<Page<MemberRead> | null>(`/schools/${schoolId}/members?size=1`, null)
      : Promise.resolve<Page<MemberRead> | null>(null),
    schoolId && hasPermission(user, PERMISSIONS.invitationRead)
      ? serverGet<InvitationRead[]>(`/schools/${schoolId}/invitations`, [])
      : Promise.resolve<InvitationRead[]>([]),
    // Gated per section on the server; a caller with none of the permissions gets
    // an all-null board, which renders as nothing.
    serverGet<DashboardAnalytics | null>("/dashboard/analytics", null),
  ]);

  const pendingInvites = invitations.filter((i) => i.status === "pending");

  return (
    <div className="mx-auto w-full max-w-6xl">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">
          {t.dashboard.welcome}, {user.full_name.split(" ")[0]}
        </h1>
        <p className="mt-1 text-muted-foreground">
          {user.school_name
            ? `${user.school_name} · ${user.role_code}`
            : `${user.organization_name} · ${t.dashboard.organizationView}`}
        </p>
      </header>

      {analytics ? (
        <div className="mb-8">
          <AnalyticsBoard data={analytics} />
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-3">
        <Can permission={PERMISSIONS.schoolRead}>
          <StatCard icon={Building2} label={t.nav.schools} value={schools.length} href="/schools" />
        </Can>
        {schoolId ? (
          <>
            <Can permission={PERMISSIONS.memberRead}>
              <StatCard icon={Users} label={t.nav.members} value={members?.meta.total ?? 0} href="/members" />
            </Can>
            <Can permission={PERMISSIONS.invitationRead}>
              <StatCard
                icon={Mail}
                label={t.nav.invitations}
                value={pendingInvites.length}
                href="/members?invite=1"
              />
            </Can>
          </>
        ) : null}
      </div>

      {usage ? (
        <section className="mt-8">
          <h2 className="mb-3 text-sm font-medium text-muted-foreground">
            {t.dashboard.planUsage} · {usage.plan_code}
          </h2>
          <UsageCard usage={usage} />
        </section>
      ) : null}

      {/* Shown only when there is genuinely nothing else to do. A principal who has
          just verified their email and has no school yet needs one obvious next step,
          not a grid of zeroes. */}
      {schools.length === 0 && hasPermission(user, PERMISSIONS.schoolCreate) ? (
        <section className="mt-8 rounded-xl border border-dashed border-border p-8 text-center">
          <h2 className="font-medium">{t.dashboard.firstSchoolTitle}</h2>
          <p className="mx-auto mt-1.5 max-w-sm text-sm text-muted-foreground text-pretty">
            {t.dashboard.firstSchoolBody}
          </p>
          <Button asChild className="mt-5">
            <Link href="/onboarding">{t.dashboard.getStarted}</Link>
          </Button>
        </section>
      ) : null}
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  href,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number;
  // `Route`, not `string`: with `typedRoutes` on, a link to a path that does not
  // exist is a build error. Widening this to `string` would opt the whole component
  // out of that check, which is the one thing the feature is for.
  href: Route;
}) {
  return (
    <Link
      href={href}
      className="rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/50"
    >
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Icon className="size-4" aria-hidden />
        {label}
      </div>
      <p className="mt-2 text-3xl font-semibold tabular-nums">{value}</p>
    </Link>
  );
}
