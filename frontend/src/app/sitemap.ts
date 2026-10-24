import type { MetadataRoute } from "next";

import { FEATURE_SLUGS, featurePath } from "@/components/marketing/features";
import { absoluteUrl } from "@/lib/site";

/**
 * /sitemap.xml: the public pages, and only those. The tenant panel and the
 * operator console sit behind a login and are kept out (see robots.ts).
 *
 * No `lastModified`: a date that changes on every deploy whether or not the page
 * did teaches crawlers to ignore it.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: absoluteUrl("/"), changeFrequency: "weekly", priority: 1 },
    { url: absoluteUrl("/features"), changeFrequency: "monthly", priority: 0.9 },
    ...FEATURE_SLUGS.map((slug) => ({
      url: absoluteUrl(featurePath(slug)),
      changeFrequency: "monthly" as const,
      priority: 0.8,
    })),
    { url: absoluteUrl("/pricing"), changeFrequency: "monthly", priority: 0.8 },
    { url: absoluteUrl("/signup"), changeFrequency: "yearly", priority: 0.5 },
  ];
}
