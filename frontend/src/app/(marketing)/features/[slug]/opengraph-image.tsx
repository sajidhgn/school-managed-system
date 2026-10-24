import { FEATURE_SLUGS, getFeature } from "@/components/marketing/features";
import { OG_SIZE, renderOgImage } from "@/components/marketing/og-card";
import { SITE_TAGLINE } from "@/lib/site";

export const alt = `SchoolYar: ${SITE_TAGLINE}`;
export const size = OG_SIZE;
export const contentType = "image/png";

export function generateStaticParams() {
  return FEATURE_SLUGS.map((slug) => ({ slug }));
}

// Next 15 passes plain params here; Next 16 passes a promise. Awaiting covers both.
// Previews are English: crawlers and link unfurlers send no language cookie.
export default async function Image({
  params,
}: {
  params: { slug: string } | Promise<{ slug: string }>;
}) {
  const feature = getFeature((await params).slug, "en");
  return renderOgImage({
    eyebrow: feature?.eyebrow ?? SITE_TAGLINE,
    title: feature?.h1 ?? SITE_TAGLINE,
  });
}
