import {
  Building2,
  CalendarCheck,
  ClipboardList,
  FileText,
  GraduationCap,
  History,
  IdCard,
  Languages,
  MailPlus,
  MessageCircle,
  MessageSquareText,
  Receipt,
  Search,
  type LucideIcon,
} from "lucide-react";

import type { Locale } from "@/lib/i18n/config";

import { getCopy, type BiLabelText, type FeatureCopy, type FeatureSlug } from "./copy";
import { en } from "./copy-en";
import { ur } from "./copy-ur";

export type { FeatureSlug } from "./copy";

/**
 * The public feature pages, one per thing a school searches for.
 *
 * Each is its own URL (/features/<slug>) with its own title, description, FAQ and
 * structured data, so each can rank for its own search; the landing page is the
 * overview and links into them. The words live in copy-en.ts / copy-ur.ts; this
 * file holds what does not change with language.
 */

/** Which illustration a page's hero shows. */
export type FeatureDemo = "diary" | "attendance-chat" | "challan" | "pages" | "register" | "campus" | "rtl";

type FeatureMeta = {
  slug: FeatureSlug;
  icon: LucideIcon;
  demo: FeatureDemo;
  related: FeatureSlug[];
};

const META: FeatureMeta[] = [
  {
    slug: "whatsapp-diary",
    icon: MessageCircle,
    demo: "diary",
    related: ["whatsapp-attendance", "fee-management", "urdu"],
  },
  {
    slug: "whatsapp-attendance",
    icon: MessageSquareText,
    demo: "attendance-chat",
    related: ["attendance", "whatsapp-diary", "multi-campus"],
  },
  {
    slug: "fee-management",
    icon: Receipt,
    demo: "challan",
    related: ["whatsapp-diary", "multi-campus", "attendance"],
  },
  {
    slug: "test-paper-generator",
    icon: FileText,
    demo: "pages",
    related: ["urdu", "attendance", "whatsapp-diary"],
  },
  {
    slug: "attendance",
    icon: CalendarCheck,
    demo: "register",
    related: ["whatsapp-attendance", "multi-campus", "fee-management"],
  },
  {
    slug: "multi-campus",
    icon: Building2,
    demo: "campus",
    related: ["fee-management", "attendance", "urdu"],
  },
  {
    slug: "urdu",
    icon: Languages,
    demo: "rtl",
    related: ["test-paper-generator", "whatsapp-diary", "multi-campus"],
  },
];

export type Feature = FeatureMeta &
  FeatureCopy & {
    /** The feature's name in both languages, for the bilingual label. */
    label: BiLabelText;
  };

export const FEATURE_SLUGS: FeatureSlug[] = META.map((m) => m.slug);

function withCopy(meta: FeatureMeta, locale: Locale): Feature {
  return {
    ...meta,
    ...getCopy(locale).features[meta.slug],
    label: { en: en.features[meta.slug].nav, ur: ur.features[meta.slug].nav },
  };
}

export function getFeatures(locale: Locale): Feature[] {
  return META.map((meta) => withCopy(meta, locale));
}

export function getFeature(slug: string, locale: Locale): Feature | undefined {
  const meta = META.find((m) => m.slug === slug);
  return meta ? withCopy(meta, locale) : undefined;
}

export function featurePath(slug: FeatureSlug) {
  return `/features/${slug}` as const;
}

/** Icons for `copy.alsoIncluded`, in the same order. */
export const ALSO_INCLUDED_ICONS: LucideIcon[] = [ClipboardList, GraduationCap, IdCard, Search, MailPlus, History];
