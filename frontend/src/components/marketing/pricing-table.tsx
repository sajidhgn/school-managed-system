"use client";

import Link from "next/link";
import { Check, Minus } from "lucide-react";
import { useState } from "react";

import { useTranslations } from "@/components/providers/i18n-provider";
import { Button } from "@/components/ui/button";
import { USAGE_LABELS, type PlanPublic } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * The plan comparison grid.
 *
 * Everything shown — prices, limits, feature flags — comes from the API. Nothing
 * about a plan is known to this component except how to display it, so adding a
 * plan or changing a limit is a database edit, not a deploy.
 */

const FEATURE_LABELS: Record<string, string> = {
  custom_branding: "Custom branding",
  api_access: "API access",
  priority_support: "Priority support",
  sso: "Single sign-on",
  advanced_reports: "Advanced reports",
};

/** `-1` is the backend's sentinel for "no ceiling" (spec §6.1). */
function formatLimit(value: number, unlimited: string): string {
  if (value === -1) return unlimited;
  return new Intl.NumberFormat().format(value);
}

export function PricingTable({ plans }: { plans: PlanPublic[] }) {
  const { t, locale } = useTranslations();
  const [cycle, setCycle] = useState<"monthly" | "yearly">("monthly");

  const money = (amount: string | number | null | undefined, currency: string) => {
    if (amount === null || amount === undefined) return null;
    const value = typeof amount === "string" ? Number(amount) : amount;
    if (Number.isNaN(value)) return null;
    // `Intl` rather than a template string: currency placement differs by locale,
    // and under `dir="rtl"` a hand-built "$29" would render with the symbol on the
    // wrong side of the number.
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(value);
  };

  // The first plan with a real price anchors the "most popular" highlight. Marking
  // the cheapest paid tier rather than the most expensive is deliberate: the badge
  // should help a visitor choose, not upsell them.
  const highlightCode = plans.find((p) => Number(p.price_monthly ?? 0) > 0)?.code;

  return (
    <>
      <div className="mt-10 flex justify-center">
        <div
          role="radiogroup"
          aria-label="Billing period"
          className="inline-flex rounded-lg border border-border bg-card p-1"
        >
          {(["monthly", "yearly"] as const).map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={cycle === option}
              onClick={() => setCycle(option)}
              className={cn(
                "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
                cycle === option
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {option === "monthly" ? t.marketing.monthly : t.marketing.yearly}
              {option === "yearly" ? (
                <span className="ms-2 text-xs opacity-80">{t.marketing.yearlyHint}</span>
              ) : null}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-10 grid gap-6 lg:grid-cols-3">
        {plans.map((plan) => {
          const price = money(
            cycle === "monthly" ? plan.price_monthly : plan.price_yearly,
            plan.currency,
          );
          const featured = plan.code === highlightCode;

          return (
            <div
              key={plan.id}
              className={cn(
                "relative flex flex-col rounded-xl border bg-card p-6",
                featured ? "border-primary shadow-md" : "border-border",
              )}
            >
              {featured ? (
                <span className="absolute -top-3 start-6 rounded-full bg-primary px-3 py-0.5 text-xs font-medium text-primary-foreground">
                  Most popular
                </span>
              ) : null}

              <h2 className="text-lg font-semibold">{plan.name}</h2>
              {plan.marketing_tagline ? (
                <p className="mt-1 text-sm text-muted-foreground">{plan.marketing_tagline}</p>
              ) : null}

              <p className="mt-5 flex items-baseline gap-1">
                <span className="text-3xl font-semibold tracking-tight">
                  {price ?? t.marketing.contactSales}
                </span>
                {price ? (
                  <span className="text-sm text-muted-foreground">
                    {cycle === "monthly" ? t.common.perMonth : t.common.perYear}
                  </span>
                ) : null}
              </p>

              {plan.trial_days > 0 ? (
                <p className="mt-1.5 text-xs text-muted-foreground">
                  {plan.trial_days}-day free trial
                </p>
              ) : null}

              <Button asChild className="mt-6" variant={featured ? "default" : "outline"}>
                <Link href={`/signup?plan=${plan.code}`}>{t.marketing.choosePlan}</Link>
              </Button>

              <dl className="mt-7 space-y-2.5 border-t border-border pt-6 text-sm">
                {Object.entries(USAGE_LABELS).map(([key, labelText]) => {
                  const limit = plan.limits?.[key as keyof typeof plan.limits];
                  if (typeof limit !== "number") return null;
                  return (
                    <div key={key} className="flex justify-between gap-4">
                      <dt className="text-muted-foreground">{labelText}</dt>
                      <dd className="font-medium">
                        {formatLimit(limit, t.common.unlimited)}
                      </dd>
                    </div>
                  );
                })}
              </dl>

              <ul className="mt-5 space-y-2 border-t border-border pt-5 text-sm">
                {Object.entries(FEATURE_LABELS).map(([key, labelText]) => {
                  const enabled = Boolean(plan.features?.[key as keyof typeof plan.features]);
                  return (
                    <li
                      key={key}
                      className={cn(
                        "flex items-center gap-2",
                        enabled ? "" : "text-muted-foreground",
                      )}
                    >
                      {enabled ? (
                        <Check className="size-4 shrink-0 text-success" aria-hidden />
                      ) : (
                        <Minus className="size-4 shrink-0 opacity-50" aria-hidden />
                      )}
                      {/* Screen readers get the state in words; sighted users get
                          the icon. Without this, both rows read identically. */}
                      <span className="sr-only">{enabled ? "Included:" : "Not included:"}</span>
                      {labelText}
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>
    </>
  );
}
