import type { Metadata } from "next";

import { PlansView } from "./plans-view";
import { PlatformChrome } from "@/components/platform/platform-chrome";
import { serverGet } from "@/lib/api/server";
import type { OrganizationSummary, PlanAdminRead } from "@/lib/api/types";
import { requirePlatformAdmin } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Plans" };

/**
 * The product catalog, editable by operators.
 *
 * Subscriber counts are derived from the organization list rather than added to the
 * plans endpoint. The console already fetches that list, the numbers are small, and
 * keeping `GET /platform/plans` a plain catalog read means the public pricing page
 * and this page share the same shape.
 *
 * They matter here because "how many customers is this?" is the question an operator
 * needs answered BEFORE opening the editor, not only inside the save confirmation.
 */
export default async function PlansPage() {
  const admin = await requirePlatformAdmin();

  const [plans, organizations] = await Promise.all([
    serverGet<PlanAdminRead[]>("/platform/plans", [], "platform"),
    serverGet<OrganizationSummary[]>("/platform/organizations?limit=200", [], "platform"),
  ]);

  const subscriberCounts = organizations.reduce<Record<string, number>>((counts, org) => {
    if (org.plan_code) counts[org.plan_code] = (counts[org.plan_code] ?? 0) + 1;
    return counts;
  }, {});

  return (
    <PlatformChrome adminName={admin.full_name}>
      <PlansView plans={plans} subscriberCounts={subscriberCounts} />
    </PlatformChrome>
  );
}
