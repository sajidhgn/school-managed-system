import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";
import { PlatformAnalyticsBoard } from "@/components/platform/platform-analytics";
import { PlatformChrome } from "@/components/platform/platform-chrome";
import { serverGet } from "@/lib/api/server";
import type { PlatformAnalytics } from "@/lib/api/types";
import { requirePlatformAdmin } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Dashboard" };
export const dynamic = "force-dynamic";

/**
 * The console's landing page: growth, revenue, plan mix and the accounts that need
 * an operator this week. Replaces the old Metrics page, which showed the totals
 * without any of the trend or the names behind them.
 *
 * `serverGet` (not `...Required`): the dashboard is read-only, so a failed read
 * degrades to a message rather than an error page — the rest of the console stays
 * one click away.
 */
export default async function PlatformDashboardPage() {
  const admin = await requirePlatformAdmin();
  const data = await serverGet<PlatformAnalytics | null>("/platform/analytics", null, "platform");

  return (
    <PlatformChrome adminName={admin.full_name}>
      <PageHeader title="Dashboard" description="Across the whole platform." />
      {data ? (
        <PlatformAnalyticsBoard data={data} />
      ) : (
        <p className="text-muted-foreground">Analytics are temporarily unavailable.</p>
      )}
    </PlatformChrome>
  );
}
