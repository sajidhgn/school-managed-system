import type { Metadata } from "next";

import { Breadcrumbs } from "@/components/marketing/breadcrumbs";
import { LABELS, getCopy } from "@/components/marketing/copy";
import { CtaBand } from "@/components/marketing/cta-band";
import { FeatureCard } from "@/components/marketing/feature-card";
import { ALSO_INCLUDED_ICONS, featurePath, getFeatures, type FeatureSlug } from "@/components/marketing/features";
import { Hero } from "@/components/marketing/hero";
import { JsonLd } from "@/components/marketing/json-ld";
import { Stagger, StaggerItem } from "@/components/marketing/motion/reveal";
import { Section, SectionHeading } from "@/components/marketing/section";
import { getLocale } from "@/lib/i18n/server";
import { absoluteUrl, pageMetadata } from "@/lib/site";

export async function generateMetadata(): Promise<Metadata> {
  const { featuresIndex } = getCopy(await getLocale());
  return pageMetadata({
    title: featuresIndex.metaTitle,
    description: featuresIndex.metaDescription,
    path: "/features",
  });
}

/** The same two groups as the header's Features menu. */
const GROUPS: { key: "aiGroup" | "officeGroup"; slugs: FeatureSlug[] }[] = [
  { key: "aiGroup", slugs: ["whatsapp-diary", "whatsapp-attendance", "test-paper-generator"] },
  { key: "officeGroup", slugs: ["fee-management", "attendance", "multi-campus", "urdu"] },
];

export default async function FeaturesPage() {
  const locale = await getLocale();
  const copy = getCopy(locale);
  const { common, featuresIndex, nav } = copy;
  const features = getFeatures(locale);

  return (
    <div className="mk-heroui">
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "BreadcrumbList",
          itemListElement: [
            { "@type": "ListItem", position: 1, name: common.home, item: absoluteUrl("/") },
            { "@type": "ListItem", position: 2, name: common.features, item: absoluteUrl("/features") },
          ],
        }}
      />
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "ItemList",
          itemListElement: features.map((feature, i) => ({
            "@type": "ListItem",
            position: i + 1,
            name: feature.nav,
            url: absoluteUrl(featurePath(feature.slug)),
          })),
        }}
      />

      <Hero
        label={LABELS.features}
        title={featuresIndex.title}
        lede={featuresIndex.lede}
        common={common}
        breadcrumbs={<Breadcrumbs items={[{ href: "/", label: common.home }, { label: common.features }]} />}
      />

      {GROUPS.map(({ key, slugs }, g) => (
        <Section key={key} tone={g === 0 ? "paper" : "fog"}>
          <SectionHeading title={nav[key]} />
          <Stagger as="ul" className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" gap={0.07}>
            {slugs.map((slug) => {
              const feature = features.find((f) => f.slug === slug)!;
              return (
                <StaggerItem as="li" key={slug}>
                  <FeatureCard feature={feature} more={common.readMore} />
                </StaggerItem>
              );
            })}
          </Stagger>
        </Section>
      ))}

      <Section>
        <SectionHeading label={LABELS.also} title={common.alsoIncluded} />
        <Stagger as="ul" className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-3" gap={0.05}>
          {copy.alsoIncluded.map((label, i) => {
            const Icon = ALSO_INCLUDED_ICONS[i]!;
            return (
              <StaggerItem as="li" key={label} className="mk-chiprow">
                <span className="mk-iconbox">
                  <Icon className="size-4.5" aria-hidden />
                </span>
                <span>{label}</span>
              </StaggerItem>
            );
          })}
        </Stagger>
      </Section>

      <CtaBand copy={copy} />
    </div>
  );
}
