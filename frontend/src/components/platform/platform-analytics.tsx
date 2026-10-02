"use client";

import type { Route } from "next";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Clock, Minus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  ORG_STATUS_LABELS,
  label,
  type OrganizationWatch,
  type PlatformAnalytics,
} from "@/lib/api/types";
import { cn, formatDate } from "@/lib/utils";

/**
 * The operator dashboard.
 *
 * Same drawing approach as the tenant dashboard (`components/dashboard/analytics.tsx`):
 * hand-drawn SVG and flex boxes, no charting library. Colour follows the job:
 *
 *   magnitude   one hue (`chart-1`) — signups, revenue, plan subscribers. Every
 *               chart here is a single series, so the panel title names it and
 *               there is no legend box.
 *   state       success / warning / destructive / muted — organization status,
 *               always with a text label and count beside the swatch.
 *
 * Money is never summed across currencies: MRR is listed per currency, and the
 * revenue chart is drawn in `revenue_currency` only (the server picks it).
 */
export function PlatformAnalyticsBoard({ data }: { data: PlatformAnalytics }) {
  return (
    <div className="space-y-4">
      <KpiRow data={data} />

      <div className="grid gap-4 lg:grid-cols-2">
        <GrowthCard data={data} />
        <RevenueCard data={data} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <StatusCard data={data} />
        <PlansCard data={data} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <WatchCard
          title="Trials ending"
          hint="Next 14 days — the conversion conversations to have now."
          empty="No trials end in the next two weeks."
          icon={Clock}
          rows={data.trials_ending}
          when={(row) => relativeDays(row.at)}
        />
        <WatchCard
          title="Needs attention"
          hint="Past due on payment, or over their plan's limits."
          empty="Nobody is past due or over their limits."
          icon={AlertTriangle}
          rows={data.at_risk}
          when={(row) => label(ORG_STATUS_LABELS, row.status ?? "")}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <TopOrganizationsCard data={data} />
        <RecentCard data={data} />
      </div>

      <p className="text-xs text-muted-foreground">
        Updated {new Date(data.generated_at).toLocaleString()}. Churn is cumulative (share of all
        organizations now cancelled), not a period rate.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared pieces
// ---------------------------------------------------------------------------

function Panel({
  title,
  hint,
  children,
  className,
  action,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
}) {
  return (
    <section className={cn("relative rounded-xl border border-border bg-card p-5", className)}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium">{title}</h2>
          {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
        </div>
        {action}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

type Tip = { x: number; y: number; content: ReactNode } | null;

/** Positions a tooltip above the hovered mark, relative to the nearest Panel. */
function useTip() {
  const [tip, setTip] = useState<Tip>(null);
  const show = (event: React.MouseEvent<Element> | React.FocusEvent<Element>, content: ReactNode) => {
    const target = event.currentTarget.getBoundingClientRect();
    const host = (event.currentTarget as Element).closest("section")?.getBoundingClientRect();
    if (!host) return;
    setTip({ x: target.left - host.left + target.width / 2, y: target.top - host.top, content });
  };
  const node = tip ? (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-md"
      style={{ left: tip.x, top: tip.y - 6 }}
    >
      {tip.content}
    </div>
  ) : null;
  return { show, hide: () => setTip(null), node };
}

function money(value: number | string, currency: string, compact = false): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: compact ? 1 : 0,
      ...(compact ? { notation: "compact" as const } : {}),
    }).format(Number(value));
  } catch {
    // An unknown ISO code throws; show the number rather than nothing.
    return `${currency} ${Number(value).toLocaleString()}`;
  }
}

function monthLabel(key: string, long = false): string {
  const [year, month] = key.split("-").map(Number);
  return new Date(Date.UTC(year!, month! - 1, 1)).toLocaleDateString(undefined, {
    month: long ? "long" : "short",
    ...(long ? { year: "numeric" as const } : {}),
    timeZone: "UTC",
  });
}

function relativeDays(value: string | null | undefined): string {
  if (!value) return "—";
  const days = Math.round((new Date(value).getTime() - Date.now()) / 86_400_000);
  if (days < 0) return "Ended";
  if (days === 0) return "Today";
  return days === 1 ? "Tomorrow" : `In ${days} days`;
}

function orgHref(id: string): Route {
  return `/platform/organizations/${id}` as Route;
}

// ---------------------------------------------------------------------------
// KPI tiles
// ---------------------------------------------------------------------------

function Tile({ label: tileLabel, value, children }: { label: string; value: string; children?: ReactNode }) {
  return (
    <section className="flex flex-col rounded-xl border border-border bg-card p-5">
      <h2 className="text-sm text-muted-foreground">{tileLabel}</h2>
      <p className="mt-2 text-3xl font-semibold tabular-nums">{value}</p>
      <div className="mt-auto space-y-0.5 pt-3 text-xs text-muted-foreground">{children}</div>
    </section>
  );
}

function KpiRow({ data }: { data: PlatformAnalytics }) {
  const [primary, ...others] = data.mrr_by_currency;
  const delta = data.organizations_new_30d - data.organizations_new_prev_30d;
  const DeltaIcon = delta === 0 ? Minus : delta > 0 ? ArrowUpRight : ArrowDownRight;

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Tile label="Monthly recurring revenue" value={primary ? money(primary.mrr, primary.currency) : "—"}>
        {primary ? <p>{money(primary.arr, primary.currency)} annualised</p> : <p>No paying subscriptions yet.</p>}
        {others.map((row) => (
          <p key={row.currency}>
            + <span className="font-medium text-foreground">{money(row.mrr, row.currency)}</span> MRR
          </p>
        ))}
      </Tile>

      <Tile label="Organizations" value={data.organizations_total.toLocaleString()}>
        <p
          className={cn(
            "flex items-center gap-1",
            delta > 0 && "text-success",
            delta < 0 && "text-destructive",
          )}
        >
          <DeltaIcon className="size-3.5" aria-hidden />
          {data.organizations_new_30d} new in 30 days ({delta >= 0 ? "+" : "−"}
          {Math.abs(delta)} vs previous 30)
        </p>
      </Tile>

      <Tile label="Paying organizations" value={data.paying_organizations.toLocaleString()}>
        <p>{data.trialing_organizations} on trial</p>
        <p className={cn(data.failed_payments_30d > 0 && "text-destructive")}>
          {data.failed_payments_30d} failed payment{data.failed_payments_30d === 1 ? "" : "s"} in 30
          days
        </p>
      </Tile>

      <Tile label="Students on the platform" value={data.students_total.toLocaleString()}>
        <p>
          {data.schools_total.toLocaleString()} schools · {data.staff_total.toLocaleString()} staff
          seats
        </p>
        <p>Churn {(data.churn_rate * 100).toFixed(1)}% (cumulative)</p>
      </Tile>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Monthly bars: one series, baseline-anchored, rounded data end, hover tooltip.
// ---------------------------------------------------------------------------

function MonthlyBars({
  points,
  value,
  tip,
  format,
  ariaLabel,
}: {
  points: { month: string }[];
  value: (index: number) => number;
  tip: (index: number) => ReactNode;
  format: (n: number) => string;
  ariaLabel: string;
}) {
  const { show, hide, node } = useTip();
  const values = points.map((_, i) => value(i));
  const max = Math.max(...values, 0);
  const peak = values.indexOf(max);

  return (
    <>
      <div className="flex h-40 items-end gap-1" role="img" aria-label={ariaLabel}>
        {points.map((point, i) => {
          const height = max > 0 ? (values[i]! / max) * 100 : 0;
          return (
            <button
              key={point.month}
              type="button"
              className="group flex h-full flex-1 flex-col items-center justify-end gap-1 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onMouseEnter={(e) => show(e, tip(i))}
              onFocus={(e) => show(e, tip(i))}
              onMouseLeave={hide}
              onBlur={hide}
              aria-label={`${monthLabel(point.month, true)}: ${format(values[i]!)}`}
            >
              {/* Direct label on the peak only — a number on every bar is noise. */}
              {i === peak && max > 0 ? (
                <span className="text-[10px] font-medium tabular-nums text-muted-foreground">
                  {format(values[i]!)}
                </span>
              ) : null}
              <span
                className={cn(
                  "w-full max-w-8 rounded-t-[4px] transition-opacity group-hover:opacity-80",
                  values[i]! > 0 ? "bg-chart-1" : "bg-muted",
                )}
                style={{ height: values[i]! > 0 ? `max(${height}%, 3px)` : "2px" }}
              />
            </button>
          );
        })}
      </div>
      <div className="mt-2 flex gap-1 border-t border-border pt-1.5">
        {points.map((point, i) => (
          <span key={point.month} className="flex-1 text-center text-[10px] text-muted-foreground">
            {/* Every other month on narrow screens keeps the axis legible. */}
            <span className={cn(i % 2 === 1 && "max-sm:invisible")}>{monthLabel(point.month)}</span>
          </span>
        ))}
      </div>
      {node}
    </>
  );
}

function GrowthCard({ data }: { data: PlatformAnalytics }) {
  const total = data.growth.reduce((sum, p) => sum + p.organizations, 0);
  return (
    <Panel title="New organizations" hint={`${total} signed up in the last 12 months.`}>
      <MonthlyBars
        points={data.growth}
        value={(i) => data.growth[i]!.organizations}
        format={(n) => n.toLocaleString()}
        ariaLabel="New organizations per month, last 12 months"
        tip={(i) => {
          const p = data.growth[i]!;
          return (
            <>
              <p className="font-medium">{monthLabel(p.month, true)}</p>
              <p>
                {p.organizations} organization{p.organizations === 1 ? "" : "s"} · {p.schools} school
                {p.schools === 1 ? "" : "s"}
              </p>
            </>
          );
        }}
      />
    </Panel>
  );
}

function RevenueCard({ data }: { data: PlatformAnalytics }) {
  const currency = data.revenue_currency;
  const total = data.revenue.reduce((sum, p) => sum + Number(p.collected), 0);
  const failed = data.revenue.reduce((sum, p) => sum + p.failed, 0);
  return (
    <Panel
      title={`Revenue collected (${currency})`}
      hint={`${money(total, currency)} over 12 months${failed ? ` · ${failed} failed payments` : ""}.`}
    >
      <MonthlyBars
        points={data.revenue}
        value={(i) => Number(data.revenue[i]!.collected)}
        format={(n) => money(n, currency, true)}
        ariaLabel={`Revenue collected per month in ${currency}, last 12 months`}
        tip={(i) => {
          const p = data.revenue[i]!;
          return (
            <>
              <p className="font-medium">{monthLabel(p.month, true)}</p>
              <p>{money(p.collected, currency)} collected</p>
              <p className="text-muted-foreground">
                {p.succeeded} succeeded · {p.failed} failed
              </p>
            </>
          );
        }}
      />
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Organization status: a 100% bar in status colours, every segment labelled.
// ---------------------------------------------------------------------------

const STATUS_ORDER = [
  { key: "active", color: "bg-success" },
  { key: "trialing", color: "bg-chart-1" },
  { key: "past_due", color: "bg-warning" },
  { key: "over_limit", color: "bg-warning/50" },
  { key: "suspended", color: "bg-destructive" },
  { key: "cancelled", color: "bg-muted-foreground/40" },
] as const;

function StatusCard({ data }: { data: PlatformAnalytics }) {
  const { show, hide, node } = useTip();
  const counts = data.organizations_by_status;
  const total = data.organizations_total;
  const parts = STATUS_ORDER.filter((s) => (counts[s.key] ?? 0) > 0);

  return (
    <Panel title="Organizations by status" hint="Where every account sits in its lifecycle.">
      {total === 0 ? (
        <p className="text-sm text-muted-foreground">No organizations yet.</p>
      ) : (
        <>
          <div className="flex h-3 gap-0.5 overflow-hidden rounded-full" role="img" aria-label="Organizations by status">
            {parts.map((s) => (
              <div
                key={s.key}
                tabIndex={0}
                className={cn("h-full first:rounded-s-full last:rounded-e-full outline-none", s.color)}
                style={{ width: `${((counts[s.key] ?? 0) / total) * 100}%` }}
                onMouseEnter={(e) => show(e, `${label(ORG_STATUS_LABELS, s.key)}: ${counts[s.key]}`)}
                onFocus={(e) => show(e, `${label(ORG_STATUS_LABELS, s.key)}: ${counts[s.key]}`)}
                onMouseLeave={hide}
                onBlur={hide}
              />
            ))}
          </div>
          <ul className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            {STATUS_ORDER.map((s) => (
              <li key={s.key} className="flex items-center gap-2">
                <span className={cn("size-2.5 shrink-0 rounded-full", s.color)} aria-hidden />
                <Link
                  href={`/platform/organizations?status=${s.key}` as Route}
                  className="text-muted-foreground hover:text-foreground hover:underline"
                >
                  {label(ORG_STATUS_LABELS, s.key)}
                </Link>
                <span className="ms-auto font-medium tabular-nums">{counts[s.key] ?? 0}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {node}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Plan mix: subscribers per plan as horizontal bars, MRR beside each.
// ---------------------------------------------------------------------------

function PlansCard({ data }: { data: PlatformAnalytics }) {
  const max = Math.max(...data.plans.map((p) => p.subscribers), 0);
  return (
    <Panel
      title="Subscribers by plan"
      hint="Bars are organizations on each plan; MRR counts paying ones only."
      action={
        <Link href="/platform/plans" className="text-xs text-muted-foreground hover:text-foreground hover:underline">
          Manage plans
        </Link>
      }
    >
      {data.plans.length === 0 ? (
        <p className="text-sm text-muted-foreground">No plans in the catalog.</p>
      ) : (
        <ul className="space-y-3">
          {data.plans.map((plan) => (
            <li key={plan.plan_id} className="grid grid-cols-[7rem_minmax(0,1fr)_auto] items-center gap-3 text-sm">
              <span className="truncate" title={plan.code}>
                {plan.name}
              </span>
              <span className="flex items-center gap-2">
                <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
                  <span
                    className="block h-full rounded-full bg-chart-1"
                    style={{ width: max > 0 ? `${(plan.subscribers / max) * 100}%` : "0%" }}
                  />
                </span>
                <span className="w-8 text-end font-medium tabular-nums">{plan.subscribers}</span>
              </span>
              <span className="w-24 text-end text-xs tabular-nums text-muted-foreground">
                {Number(plan.mrr) > 0 ? `${money(plan.mrr, plan.currency)}/mo` : "—"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Lists
// ---------------------------------------------------------------------------

function WatchCard({
  title,
  hint,
  empty,
  icon: Icon,
  rows,
  when,
}: {
  title: string;
  hint: string;
  empty: string;
  icon: typeof Clock;
  rows: OrganizationWatch[];
  when: (row: OrganizationWatch) => string;
}) {
  return (
    <Panel title={title} hint={hint}>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((row) => (
            <li key={row.organization_id} className="flex items-center gap-3 py-2.5 text-sm first:pt-0 last:pb-0">
              <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <div className="min-w-0 flex-1">
                <Link href={orgHref(row.organization_id)} className="block truncate font-medium hover:underline">
                  {row.name}
                </Link>
                <p className="truncate text-xs text-muted-foreground">{row.plan_name ?? "No plan"}</p>
              </div>
              <span className="shrink-0 text-xs text-muted-foreground">{when(row)}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function TopOrganizationsCard({ data }: { data: PlatformAnalytics }) {
  return (
    <Panel title="Largest organizations" hint="By enrolled students.">
      {data.top_organizations.length === 0 ? (
        <p className="text-sm text-muted-foreground">No usage recorded yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-muted-foreground">
              <th className="pb-2 text-start font-normal">Organization</th>
              <th className="pb-2 text-end font-normal">Students</th>
              <th className="pb-2 text-end font-normal">Staff</th>
              <th className="pb-2 text-end font-normal">Schools</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data.top_organizations.map((org) => (
              <tr key={org.organization_id}>
                <td className="max-w-0 py-2">
                  <Link href={orgHref(org.organization_id)} className="block truncate font-medium hover:underline">
                    {org.name}
                  </Link>
                  <span className="block truncate text-xs text-muted-foreground">{org.plan_name ?? "No plan"}</span>
                </td>
                <td className="py-2 text-end tabular-nums">{org.students.toLocaleString()}</td>
                <td className="py-2 text-end tabular-nums">{org.staff.toLocaleString()}</td>
                <td className="py-2 text-end tabular-nums">{org.schools.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function statusVariant(status: string) {
  if (status === "active" || status === "trialing") return "success" as const;
  if (status === "suspended" || status === "cancelled") return "destructive" as const;
  return "warning" as const;
}

function RecentCard({ data }: { data: PlatformAnalytics }) {
  return (
    <Panel
      title="Recent signups"
      action={
        <Link href="/platform/organizations" className="text-xs text-muted-foreground hover:text-foreground hover:underline">
          All organizations
        </Link>
      }
    >
      {data.recent_organizations.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nobody has signed up yet.</p>
      ) : (
        <ul className="divide-y divide-border">
          {data.recent_organizations.map((org) => (
            <li key={org.organization_id} className="flex items-center gap-3 py-2.5 text-sm first:pt-0 last:pb-0">
              <div className="min-w-0 flex-1">
                <Link href={orgHref(org.organization_id)} className="block truncate font-medium hover:underline">
                  {org.name}
                </Link>
                <p className="truncate text-xs text-muted-foreground">
                  {org.plan_name ?? "No plan"} · {formatDate(org.created_at)}
                </p>
              </div>
              <Badge variant={statusVariant(org.status)}>{label(ORG_STATUS_LABELS, org.status)}</Badge>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
