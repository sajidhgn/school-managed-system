import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { OrganizationDetailView } from "./organization-detail-view";
import { PlatformChrome } from "@/components/platform/platform-chrome";
import { serverGetOrNull, serverGetRequired } from "@/lib/api/server";
import type { OrganizationDetail, PlanAdminRead, SchoolRead } from "@/lib/api/types";
import { requirePlatformAdmin } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Organization" };
export const dynamic = "force-dynamic";

/**
 * One organization: its billing/plan facts plus the schools that make up its
 * `schools_count`. The organizations table only ever showed that count as a number;
 * this is where an operator sees which campuses it actually refers to.
 */
export default async function OrganizationDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ supportUntil?: string }>;
}) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const admin = await requirePlatformAdmin();

  const organization = await serverGetOrNull<OrganizationDetail>(
    `/platform/organizations/${id}`,
    "platform",
  );
  if (!organization) notFound();

  const [schools, plans] = await Promise.all([
    serverGetRequired<SchoolRead[]>(`/platform/organizations/${id}/schools`, "platform"),
    serverGetRequired<PlanAdminRead[]>("/platform/plans", "platform"),
  ]);

  return (
    <PlatformChrome adminName={admin.full_name}>
      <OrganizationDetailView
        organization={organization}
        schools={schools}
        plans={plans}
        supportUntil={query.supportUntil ?? null}
      />
    </PlatformChrome>
  );
}
