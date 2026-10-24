import type { Metadata } from "next";

import { LABELS, getCopy } from "@/components/marketing/copy";
import { CtaBand } from "@/components/marketing/cta-band";
import { Faq } from "@/components/marketing/faq";
import { Hero } from "@/components/marketing/hero";
import { JsonLd } from "@/components/marketing/json-ld";
import { Reveal } from "@/components/marketing/motion/reveal";
import { PricingTable } from "@/components/marketing/pricing-table";
import { Section, SectionHeading } from "@/components/marketing/section";
import { API_BASE_URL, API_V1_PREFIX } from "@/lib/api/config";
import type { PlanPublic } from "@/lib/api/types";
import { getLocale, getTranslations } from "@/lib/i18n/server";
import { demoUrl, pageMetadata } from "@/lib/site";

// No figures in the description: like the page, it must not hardcode a price.
export async function generateMetadata(): Promise<Metadata> {
  const copy = getCopy(await getLocale());
  return pageMetadata({
    title: copy.common.pricing,
    description: copy.pricing.metaDescription,
    path: "/pricing",
  });
}

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
  const [t, locale] = await Promise.all([getTranslations(), getLocale()]);
  const copy = getCopy(locale);
  const { pricing, common } = copy;
  const contactHref = demoUrl(common.demoMessage);

  const response = await fetch(`${API_BASE_URL}${API_V1_PREFIX}/public/plans`, {
    next: { revalidate: 300 },
  });

  // A pricing page that 500s because the API is briefly unavailable is worse than
  // one that renders its heading and an apology — this is the page prospective
  // customers arrive on from search.
  const plans: PlanPublic[] = response.ok ? await response.json() : [];

  return (
    <div className="mk-heroui">
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "FAQPage",
          mainEntity: pricing.faqs.map(([q, a]) => ({
            "@type": "Question",
            name: q,
            acceptedAnswer: { "@type": "Answer", text: a },
          })),
        }}
      />
      <Hero
        center
        actions={false}
        label={LABELS.pricing}
        title={t.marketing.pricingTitle}
        lede={t.marketing.pricingSubtitle}
        common={common}
      />

      {/* The plans rise over the hero's foot. */}
      <div className="mk-container relative z-10 -mt-36 pb-20">
        {plans.length > 0 ? (
          <PricingTable plans={plans} />
        ) : (
          <p className="pt-24 text-center text-mk-muted">{pricing.unavailable}</p>
        )}

        {/* Only with a way to reach the team: never a placeholder address. */}
        {contactHref ? (
          <Reveal as="p" className="mt-14 text-center text-sm text-mk-muted">
            {pricing.groups.before}
            <a href={contactHref} target="_blank" rel="noopener noreferrer" className="mk-textlink">
              {pricing.groups.link}
            </a>
            {pricing.groups.after}
          </Reveal>
        ) : null}
      </div>

      <Section id="questions" tone="fog">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)]">
          <SectionHeading label={LABELS.questions} title={common.questionsTitle} />
          <Reveal>
            <Faq items={pricing.faqs} />
          </Reveal>
        </div>
      </Section>

      <CtaBand copy={copy} />
    </div>
  );
}
