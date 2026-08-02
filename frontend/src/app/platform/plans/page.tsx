import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";
import { PlatformChrome } from "@/components/platform/platform-chrome";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { serverGet } from "@/lib/api/server";
import { USAGE_LABELS, type PlanAdminRead } from "@/lib/api/types";
import { requirePlatformAdmin } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Plans" };

/**
 * The product catalog, as the operator sees it — including hidden and retired plans.
 *
 * This table is the SOURCE OF TRUTH for the public pricing page and for every
 * entitlement check. Editing a limit here changes what customers can create; editing
 * a price changes what they are charged. That is why prices are never duplicated
 * into the marketing site.
 *
 * Read-only in this release. Plan editing exists on the API
 * (`POST/PATCH/DELETE /platform/plans`) and is deliberately not wired to a form yet:
 * a mistyped limit silently blocks every customer on that plan, and the mistake is
 * invisible until support tickets arrive. It wants a confirmation flow showing the
 * blast radius — how many organizations are affected — which is a piece of work in
 * its own right rather than a text input.
 */
export default async function PlansPage() {
  const admin = await requirePlatformAdmin();
  const plans = await serverGet<PlanAdminRead[]>("/platform/plans", [], "platform");

  return (
    <PlatformChrome adminName={admin.full_name}>
      <PageHeader
        title="Plans"
        description="What the pricing page shows and what entitlements enforce."
      />

      <div className="rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Plan</TableHead>
              <TableHead>Price</TableHead>
              <TableHead>Trial</TableHead>
              {Object.values(USAGE_LABELS).map((limitLabel) => (
                <TableHead key={limitLabel} className="text-end">
                  {limitLabel}
                </TableHead>
              ))}
              <TableHead>Visibility</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {plans.map((plan) => (
              <TableRow key={plan.id}>
                <TableCell>
                  <div className="font-medium">{plan.name}</div>
                  <code className="text-xs text-muted-foreground">{plan.code}</code>
                </TableCell>
                <TableCell className="whitespace-nowrap tabular-nums">
                  {plan.price_monthly === null
                    ? "Custom"
                    : `${plan.currency} ${plan.price_monthly}/mo`}
                </TableCell>
                <TableCell className="tabular-nums">
                  {plan.trial_days > 0 ? `${plan.trial_days}d` : "—"}
                </TableCell>
                {Object.keys(USAGE_LABELS).map((key) => {
                  const value = Number(plan.limits?.[key] ?? 0);
                  return (
                    <TableCell key={key} className="text-end tabular-nums">
                      {/* -1 is the unlimited sentinel; rendering it raw would read
                          as a data error. */}
                      {value === -1 ? "∞" : value.toLocaleString()}
                    </TableCell>
                  );
                })}
                <TableCell>
                  <div className="flex gap-1">
                    {plan.is_public ? (
                      <Badge variant="success">Public</Badge>
                    ) : (
                      <Badge variant="neutral">Hidden</Badge>
                    )}
                    {!plan.is_active ? <Badge variant="destructive">Retired</Badge> : null}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <p className="mt-4 text-sm text-muted-foreground">
        Hidden plans are assignable to a specific organization from its detail page, but never
        selectable by customers themselves.
      </p>
    </PlatformChrome>
  );
}
