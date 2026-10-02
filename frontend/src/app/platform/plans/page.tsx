import type { Metadata } from "next";

import { PlansView } from "./plans-view";
import { PlatformChrome } from "@/components/platform/platform-chrome";
import { serverGetOrNull, serverGetRequired } from "@/lib/api/server";
import type { PlanAdminRead, PlatformAnalytics } from "@/lib/api/types";
import { requirePlatformAdmin } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Plans" };

export const dynamic = "force-dynamic";

/**
 * The product catalog, editable by operators.
 *
 * Subscriber counts come from the analytics read, which counts every subscription
 * server-side. They used to be derived from the first 200 organizations, which
 * silently undercounted the moment the platform grew past that.
 *
 * They matter here because "how many customers is this?" is the question an operator
 * needs answered BEFORE opening the editor, not only inside the save confirmation.
 */
export default async function PlansPage() {
  const admin = await requirePlatformAdmin();

  const [plans, analytics] = await Promise.all([
    serverGetRequired<PlanAdminRead[]>("/platform/plans", "platform"),
    serverGetOrNull<PlatformAnalytics>("/platform/analytics", "platform"),
  ]);

  const subscriberCounts = Object.fromEntries(
    (analytics?.plans ?? []).map((plan) => [plan.code, plan.subscribers]),
  );

  return (
    <PlatformChrome adminName={admin.full_name}>
      <PlansView plans={plans} subscriberCounts={subscriberCounts} />
    </PlatformChrome>
  );
}
