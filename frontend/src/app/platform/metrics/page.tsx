import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";
import { PlatformChrome } from "@/components/platform/platform-chrome";
import { serverGet } from "@/lib/api/server";
import { ORG_STATUS_LABELS, label, type MetricsResponse } from "@/lib/api/types";
import { requirePlatformAdmin } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Metrics" };

/**
 * Platform-wide numbers.
 *
 * MRR is computed server-side by normalising each subscription to a monthly figure —
 * a yearly plan contributes one twelfth. Summing raw prices across mixed billing
 * cycles is the standard way to overstate MRR by an order of magnitude the moment
 * annual plans start selling, so the number here is the normalised one.
 *
 * Churn is CUMULATIVE (share of all organizations ever created that are now
 * cancelled), not period churn — which needs a cohort window. Labelled as such,
 * because an unqualified "churn" on a dashboard gets quoted in board decks.
 */
export default async function MetricsPage() {
  const admin = await requirePlatformAdmin();
  const metrics = await serverGet<MetricsResponse | null>("/platform/metrics", null, "platform");

  if (!metrics) {
    return (
      <PlatformChrome adminName={admin.full_name}>
        <PageHeader title="Metrics" />
        <p className="text-muted-foreground">Metrics are temporarily unavailable.</p>
      </PlatformChrome>
    );
  }

  return (
    <PlatformChrome adminName={admin.full_name}>
      <PageHeader title="Metrics" description="Across the whole platform." />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="MRR" value={`$${metrics.mrr}`} hint="Normalised to monthly" />
        <Metric label="Organizations" value={metrics.organizations_total} />
        <Metric label="Schools" value={metrics.schools_total} />
        <Metric label="Staff seats" value={metrics.staff_seats_total} />
        <Metric
          label="Failed payments"
          value={metrics.failed_payments_30d}
          hint="Last 30 days"
        />
        <Metric
          label="Churn"
          value={`${(metrics.churn_rate * 100).toFixed(1)}%`}
          hint="Cumulative, not period"
        />
      </div>

      <section className="mt-8">
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">
          Organizations by status
        </h2>
        <div className="grid gap-2 sm:grid-cols-3">
          {Object.entries(metrics.organizations_by_status).map(([status, count]) => (
            <div
              key={status}
              className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3"
            >
              <span className="text-sm text-muted-foreground">
                {label(ORG_STATUS_LABELS, status)}
              </span>
              <span className="font-semibold tabular-nums">{count}</span>
            </div>
          ))}
        </div>
      </section>
    </PlatformChrome>
  );
}

function Metric({
  label: metricLabel,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <p className="text-sm text-muted-foreground">{metricLabel}</p>
      <p className="mt-1.5 text-2xl font-semibold tabular-nums">{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
