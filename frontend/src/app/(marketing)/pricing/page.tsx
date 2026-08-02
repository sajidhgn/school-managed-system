import type { Metadata } from "next";

import { PricingTable } from "@/components/marketing/pricing-table";
import { API_BASE_URL, API_V1_PREFIX } from "@/lib/api/config";
import type { PlanPublic } from "@/lib/api/types";
import { getTranslations } from "@/lib/i18n/server";

export const metadata: Metadata = { title: "Pricing" };

/**
 * Pricing page — renders `GET /public/plans` (spec §9).
 *
 * =============================================================================
 * PRICES ARE NEVER HARDCODED HERE
 * =============================================================================
 *   Spec §6.1 is explicit about it, and the reason is concrete: a price duplicated
 *   into the marketing site is a price that will one day disagree with the one
 *   actually charged — and the customer will have a screenshot of the cheaper one.
 *
 *   So the plans, their limits and their feature flags all come from the API, which
 *   reads the same `plans` table the subscription service bills from. The super
 *   admin edits a price in the console and this page reflects it.
 *
 * Fetched server-side with a 5-minute revalidate, matching the backend's own
 * Cache-Control. The catalog changes a few times a year and this is the most-hit
 * page on the site; re-fetching per visitor would be pure waste.
 */
export default async function PricingPage() {
  const t = await getTranslations();

  const response = await fetch(`${API_BASE_URL}${API_V1_PREFIX}/public/plans`, {
    next: { revalidate: 300 },
  });

  // A pricing page that 500s because the API is briefly unavailable is worse than
  // one that renders its heading and an apology — this is the page prospective
  // customers arrive on from search.
  const plans: PlanPublic[] = response.ok ? await response.json() : [];

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
      <div className="mx-auto max-w-2xl text-center">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          {t.marketing.pricingTitle}
        </h1>
        <p className="mt-4 text-lg text-muted-foreground text-pretty">
          {t.marketing.pricingSubtitle}
        </p>
      </div>

      {plans.length > 0 ? (
        <PricingTable plans={plans} />
      ) : (
        <p className="mt-16 text-center text-muted-foreground">
          Plans are temporarily unavailable. Please try again shortly.
        </p>
      )}

      <p className="mt-14 text-center text-sm text-muted-foreground">
        Need more than the plans above?{" "}
        <a href="mailto:sales@educloud.example" className="text-primary hover:underline">
          Talk to us about Enterprise
        </a>
        .
      </p>
    </div>
  );
}
