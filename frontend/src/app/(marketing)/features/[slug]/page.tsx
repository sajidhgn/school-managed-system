import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { CSSProperties } from "react";

import { Breadcrumbs } from "@/components/marketing/breadcrumbs";
import { LABELS, getCopy } from "@/components/marketing/copy";
import { CtaBand } from "@/components/marketing/cta-band";
import { Faq } from "@/components/marketing/faq";
import { FeatureCard } from "@/components/marketing/feature-card";
import { FeatureDemo, SIDE_DEMOS } from "@/components/marketing/feature-demo";
import { FEATURE_SLUGS, featurePath, getFeature, type Feature } from "@/components/marketing/features";
import { Hero } from "@/components/marketing/hero";
import { InView } from "@/components/marketing/in-view";
import { JsonLd } from "@/components/marketing/json-ld";
import { Reveal, Stagger, StaggerItem } from "@/components/marketing/motion/reveal";
import { Spotlight } from "@/components/marketing/motion/spotlight";
import { Section, SectionHeading } from "@/components/marketing/section";
import { getLocale } from "@/lib/i18n/server";
import { absoluteUrl, pageMetadata } from "@/lib/site";

/**
 * One public page per feature (components/marketing/features.ts), each with its
 * own title, description, canonical URL, preview image and structured data, so a
 * school searching for "fee challan software" lands on the page about fees.
 */

type Props = { params: Promise<{ slug: string }> };

export const dynamicParams = false;

export function generateStaticParams() {
  return FEATURE_SLUGS.map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const feature = getFeature((await params).slug, await getLocale());
  if (!feature) return {};
  return pageMetadata({
    title: feature.metaTitle,
    description: feature.metaDescription,
    path: featurePath(feature.slug),
  });
}

const at = (i: number) => ({ "--i": i }) as CSSProperties;

export default async function FeaturePage({ params }: Props) {
  const locale = await getLocale();
  const feature = getFeature((await params).slug, locale);
  if (!feature) notFound();

  const copy = getCopy(locale);
  const { common } = copy;
  const related = feature.related
    .map((slug) => getFeature(slug, locale))
    .filter((f): f is Feature => Boolean(f));
  const path = featurePath(feature.slug);

  return (
    <div className="mk-heroui">
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "BreadcrumbList",
          itemListElement: [
            { "@type": "ListItem", position: 1, name: common.home, item: absoluteUrl("/") },
            { "@type": "ListItem", position: 2, name: common.features, item: absoluteUrl("/features") },
            { "@type": "ListItem", position: 3, name: feature.nav, item: absoluteUrl(path) },
          ],
        }}
      />
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "FAQPage",
          mainEntity: feature.faqs.map(([q, a]) => ({
            "@type": "Question",
            name: q,
            acceptedAnswer: { "@type": "Answer", text: a },
          })),
        }}
      />

      <Hero
        label={feature.label}
        title={feature.h1}
        lede={feature.lede}
        common={common}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { href: "/", label: common.home },
              { href: "/features", label: common.features },
              { label: feature.nav },
            ]}
          />
        }
        demoSide={SIDE_DEMOS.has(feature.demo)}
        demo={<FeatureDemo demo={feature.demo} copy={copy} locale={locale} />}
      />

      {/* ── How it works: a numbered sequence ─────────────────────────── */}
      {feature.steps ? (
        <Section>
          <SectionHeading label={LABELS.how} title={common.howItWorks} />
          <InView threshold={0.3}>
            <ol className="mk-flow mt-14" style={{ "--n": feature.steps.length } as CSSProperties}>
              {feature.steps.map(([title, body], i) => (
                <li key={title} className="mk-flow__step" style={at(i)}>
                  <span className="mk-flow__no" style={at(i)} aria-hidden>
                    {i + 1}
                  </span>
                  <h3 className="text-lg font-semibold">{title}</h3>
                  <p className="mt-2 leading-relaxed text-pretty text-mk-muted">{body}</p>
                </li>
              ))}
            </ol>
          </InView>
        </Section>
      ) : null}

      {/* ── Details ───────────────────────────────────────────────────── */}
      <Section tone="fog">
        <SectionHeading label={LABELS.details} title={feature.detailsTitle} />
        <Stagger as="dl" className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" gap={0.06}>
          {feature.details.map(([title, body]) => (
            <StaggerItem key={title}>
              <Spotlight className="h-full" lift={-3}>
                <div className="mk-detail">
                  <span className="mk-detail__tick" aria-hidden />
                  <dt className="font-semibold">{title}</dt>
                  <dd className="mt-1.5 leading-relaxed text-pretty text-mk-muted">{body}</dd>
                </div>
              </Spotlight>
            </StaggerItem>
          ))}
        </Stagger>
      </Section>

      {/* ── Questions ─────────────────────────────────────────────────── */}
      <Section id="questions">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)]">
          <SectionHeading
            label={LABELS.questions}
            title={common.questionsTitle}
            lede={
              <>
                {common.questionsLede.before}
                <Link href="/signup" className="mk-textlink">
                  {common.questionsLede.link}
                </Link>
                {common.questionsLede.after}
              </>
            }
          />
          <Reveal>
            <Faq items={feature.faqs} />
          </Reveal>
        </div>
      </Section>

      {/* ── See also ──────────────────────────────────────────────────── */}
      <Section tone="night">
        <SectionHeading label={LABELS.related} title={common.moreIn} />
        <Stagger as="ul" className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" gap={0.07}>
          {related.map((item) => (
            <StaggerItem as="li" key={item.slug}>
              <FeatureCard feature={item} more={common.readMore} />
            </StaggerItem>
          ))}
        </Stagger>
      </Section>

      <CtaBand copy={copy} />
    </div>
  );
}
