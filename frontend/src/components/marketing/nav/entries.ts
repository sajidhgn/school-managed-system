import { getCopy } from "@/components/marketing/copy";
import { featurePath, getFeatures, type FeatureSlug } from "@/components/marketing/features";
import type { Locale } from "@/lib/i18n/config";
import { CONTACT, demoUrl } from "@/lib/site";

import type { NavEntry, NavLink } from "./types";

/** Features by what they are built on, as the Features menu groups them. */
const AI_FEATURES: FeatureSlug[] = ["whatsapp-diary", "whatsapp-attendance", "test-paper-generator"];
const OFFICE_FEATURES: FeatureSlug[] = ["fee-management", "attendance", "multi-campus", "urdu"];

/**
 * The header's menus in the visitor's language: Product (the home page's
 * sections), Features (one page each), Pricing, and Support.
 *
 * Server-side, because the contact links come from the server's environment and,
 * as everywhere on the site, a way to reach the team that is not set is not shown.
 */
export function navEntries(locale: Locale): NavEntry[] {
  const { nav, common } = getCopy(locale);
  const features = getFeatures(locale);

  const featureLinks = (slugs: FeatureSlug[]): NavLink[] =>
    slugs.map((slug) => {
      const feature = features.find((f) => f.slug === slug)!;
      return { href: featurePath(slug), label: feature.nav, body: feature.summary, icon: slug };
    });

  const demo = demoUrl(common.demoMessage);
  const support: NavLink[] = [
    { href: "/#questions", ...nav.faq, icon: "faq" },
    { href: "/pricing#questions", ...nav.pricingFaq, icon: "billing" },
    ...(demo ? [{ href: demo, ...nav.demo, icon: "demo", external: true } as const] : []),
    ...(CONTACT.email
      ? [{ href: `mailto:${CONTACT.email}`, label: nav.email.label, body: CONTACT.email, icon: "email", external: true } as const]
      : []),
    ...(CONTACT.phone
      ? [
          {
            href: `tel:${CONTACT.phone.replace(/[^\d+]/g, "")}`,
            label: nav.phone.label,
            body: CONTACT.phone,
            icon: "phone",
            external: true,
          } as const,
        ]
      : []),
    { href: "/login", ...nav.signIn, icon: "signIn" },
  ];

  return [
    {
      kind: "menu",
      menu: {
        id: "product",
        label: nav.product,
        width: "lg",
        groups: [
          {
            title: nav.platformGroup,
            links: [
              { href: "/#platform", ...nav.overview, icon: "overview" },
              { href: "/#tour", ...nav.tour, icon: "tour" },
              { href: "/#ai", ...nav.ai, icon: "ai" },
            ],
          },
          {
            title: nav.whyGroup,
            links: [
              { href: "/#why", ...nav.why, icon: "why" },
              { href: "/#security", ...nav.security, icon: "security" },
              { href: "/#roles", ...nav.roles, icon: "roles" },
            ],
          },
        ],
        feature: { title: nav.start.label, body: nav.start.body, href: "/signup", cta: common.startFree },
      },
    },
    {
      kind: "menu",
      menu: {
        id: "features",
        label: common.features,
        width: "lg",
        groups: [
          { title: nav.aiGroup, links: featureLinks(AI_FEATURES) },
          { title: nav.officeGroup, links: featureLinks(OFFICE_FEATURES) },
        ],
        footer: { text: nav.alsoLine, href: "/features", label: common.allFeatures },
      },
    },
    { kind: "link", id: "pricing", href: "/pricing", label: common.pricing },
    {
      kind: "menu",
      menu: { id: "support", label: nav.support, width: "sm", groups: [{ title: nav.support, links: support }] },
    },
  ];
}
