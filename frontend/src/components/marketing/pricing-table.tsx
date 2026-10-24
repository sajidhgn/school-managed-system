"use client";

import { buttonVariants } from "@heroui/styles";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { ArrowRight, Check, Minus } from "lucide-react";
import { useId, useState, type KeyboardEvent } from "react";

import { EASE_OUT } from "@/components/marketing/motion/reveal";
import { useTranslations } from "@/components/providers/i18n-provider";
import type { Messages } from "@/lib/i18n/messages";
import type { PlanPublic } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * The plan comparison grid.
 *
 * Everything shown — prices, limits, feature flags — comes from the API. Nothing
 * about a plan is known to this component except how to display it, so adding a
 * plan or changing a limit is a database edit, not a deploy.
 *
 * The billing switch is a radio group with a sliding pill; switching it rolls each
 * price over to the other period's.
 */

type MarketingKey = keyof Messages["marketing"];

/** Each plan limit and feature flag, by the catalog word that names it in the
 * visitor's language. */
const LIMIT_LABELS: Record<string, MarketingKey> = {
  max_schools: "limitSchools",
  max_students: "limitStudents",
  max_staff: "limitStaff",
  max_custom_roles: "limitRoles",
  storage_mb: "limitStorage",
};

const FEATURE_LABELS: Record<string, MarketingKey> = {
  custom_branding: "featureBranding",
  api_access: "featureApi",
  priority_support: "featureSupport",
  sso: "featureSso",
  advanced_reports: "featureReports",
};

type Cycle = "monthly" | "yearly";
const CYCLES: Cycle[] = ["monthly", "yearly"];

/** `-1` is the backend's sentinel for "no ceiling" (spec §6.1). */
function formatLimit(value: number, unlimited: string): string {
  if (value === -1) return unlimited;
  return new Intl.NumberFormat().format(value);
}

export function PricingTable({ plans }: { plans: PlanPublic[] }) {
  const { t, locale } = useTranslations();
  const [cycle, setCycle] = useState<Cycle>("monthly");
  const switchId = useId();

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

  const onSwitchKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
    event.preventDefault();
    const next = cycle === "monthly" ? "yearly" : "monthly";
    setCycle(next);
    event.currentTarget.querySelector<HTMLButtonElement>(`[data-cycle="${next}"]`)?.focus();
  };

  return (
    <>
      <div className="flex justify-center">
        <div role="radiogroup" aria-label={t.marketing.billingPeriod} className="mk-switch" onKeyDown={onSwitchKey}>
          {CYCLES.map((option) => {
            const checked = cycle === option;
            return (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={checked}
                tabIndex={checked ? 0 : -1}
                data-cycle={option}
                className="mk-switch__option"
                onClick={() => setCycle(option)}
              >
                {checked ? (
                  <motion.span
                    layoutId={`${switchId}-pill`}
                    className="mk-switch__pill"
                    transition={{ type: "spring", stiffness: 420, damping: 34 }}
                    aria-hidden
                  />
                ) : null}
                <span className="relative">{option === "monthly" ? t.marketing.monthly : t.marketing.yearly}</span>
                {option === "yearly" ? <span className="mk-switch__hint">{t.marketing.yearlyHint}</span> : null}
              </button>
            );
          })}
        </div>
      </div>

      <motion.ul
        className="mt-10 grid gap-5 md:grid-cols-2 lg:grid-cols-3"
        initial="hidden"
        animate="show"
        variants={{ hidden: {}, show: { transition: { staggerChildren: 0.09, delayChildren: 0.15 } } }}
      >
        {plans.map((plan) => {
          const price = money(cycle === "monthly" ? plan.price_monthly : plan.price_yearly, plan.currency);
          const featured = plan.code === highlightCode;

          return (
            <motion.li
              key={plan.id}
              data-reveal=""
              variants={{
                hidden: { opacity: 0, y: 28 },
                show: { opacity: 1, y: 0, transition: { duration: 0.7, ease: EASE_OUT } },
              }}
              whileHover={{ y: -6 }}
              className={cn("mk-plan", featured && "mk-plan--featured mk-night")}
            >
              {featured ? (
                <>
                  <span className="mk-plan__glow" aria-hidden />
                  <span className="mk-plan__badge">{t.marketing.mostPopular}</span>
                </>
              ) : null}

              {/* An <h2>: plans sit directly under the page's h1. */}
              <h2 className="relative font-mk-display text-xl font-bold">{plan.name}</h2>
              {plan.marketing_tagline ? (
                <p className="relative mt-1.5 text-sm leading-relaxed text-mk-muted">{plan.marketing_tagline}</p>
              ) : null}

              <div className="relative mt-6 flex h-12 items-baseline gap-1.5 overflow-hidden">
                <AnimatePresence mode="popLayout" initial={false}>
                  <motion.span
                    key={`${cycle}-${price}`}
                    className="font-mk-display text-[2.4rem] leading-none font-extrabold tracking-[-0.04em]"
                    initial={{ y: 28, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    exit={{ y: -28, opacity: 0 }}
                    transition={{ type: "spring", stiffness: 320, damping: 28 }}
                  >
                    {price ?? t.marketing.contactSales}
                  </motion.span>
                </AnimatePresence>
                {price ? (
                  <span className="text-sm text-mk-muted">
                    {cycle === "monthly" ? t.common.perMonth : t.common.perYear}
                  </span>
                ) : null}
              </div>

              {plan.trial_days > 0 ? (
                <p className="relative mt-1.5 text-xs text-mk-muted">
                  {t.marketing.freeTrial.replace("{days}", String(plan.trial_days))}
                </p>
              ) : null}

              <Link
                href={`/signup?plan=${plan.code}&cycle=${cycle}`}
                className={buttonVariants({
                  variant: featured ? "primary" : "outline",
                  fullWidth: true,
                  className: cn("relative mt-6", featured && "mk-shine"),
                })}
              >
                {t.marketing.choosePlan}
                <ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden />
              </Link>

              <dl className="relative mt-7 space-y-2.5 border-t border-mk-line pt-6 text-sm">
                {Object.entries(LIMIT_LABELS).map(([key, label]) => {
                  const limit = plan.limits?.[key as keyof typeof plan.limits];
                  if (typeof limit !== "number") return null;
                  return (
                    <div key={key} className="flex justify-between gap-4">
                      <dt className="text-mk-muted">{t.marketing[label]}</dt>
                      <dd className="font-semibold">{formatLimit(limit, t.common.unlimited)}</dd>
                    </div>
                  );
                })}
              </dl>

              <ul className="relative mt-6 space-y-2.5 border-t border-mk-line pt-6 text-sm">
                {Object.entries(FEATURE_LABELS).map(([key, label]) => {
                  const enabled = Boolean(plan.features?.[key as keyof typeof plan.features]);
                  return (
                    <li key={key} className={cn("flex items-center gap-2.5", enabled ? "" : "text-mk-muted")}>
                      {enabled ? (
                        <span className="mk-tick" aria-hidden>
                          <Check className="size-3" strokeWidth={3} />
                        </span>
                      ) : (
                        <span className="mk-tick mk-tick--off" aria-hidden>
                          <Minus className="size-3" strokeWidth={3} />
                        </span>
                      )}
                      {/* Screen readers get the state in words; sighted users get
                          the icon. Without this, both rows read identically. */}
                      <span className="sr-only">{enabled ? t.marketing.included : t.marketing.notIncluded}</span>
                      {t.marketing[label]}
                    </li>
                  );
                })}
              </ul>
            </motion.li>
          );
        })}
      </motion.ul>
    </>
  );
}
