import type { Metadata } from "next";

/**
 * The public site's own address, for canonical URLs, the sitemap and Open Graph
 * tags. Server-side only, like every other value in .env.example.
 *
 * Search engines and link previews need absolute URLs, so set `SITE_URL` in every
 * deployed environment. The localhost fallback is right only in development.
 */
export const SITE_URL = (process.env.SITE_URL ?? "http://localhost:3000").replace(/\/+$/, "");

export const SITE_NAME = "SchoolYar";

export const SITE_TAGLINE = "School management, from the diary to the fee challan";

/**
 * How a visitor reaches the team, from the server's environment. Each is optional:
 * a link whose value is not set is not shown, so the site never ships a placeholder
 * number or address.
 */
export const CONTACT = {
  /** International format, digits only: 923001234567. */
  whatsapp: (process.env.SITE_WHATSAPP ?? "").replace(/\D/g, ""),
  email: (process.env.SITE_EMAIL ?? "").trim(),
  phone: (process.env.SITE_PHONE ?? "").trim(),
};

/** A WhatsApp chat with the team, opened with `message` typed in; null when unset. */
export function whatsappUrl(message: string): string | null {
  return CONTACT.whatsapp ? `https://wa.me/${CONTACT.whatsapp}?text=${encodeURIComponent(message)}` : null;
}

/** Where "Book a free demo" goes: WhatsApp, else email; null when neither is set. */
export function demoUrl(message: string): string | null {
  if (CONTACT.whatsapp) return whatsappUrl(message);
  if (CONTACT.email) return `mailto:${CONTACT.email}?subject=${encodeURIComponent(message)}`;
  return null;
}

/** Absolute URL for a site path, e.g. `/features/attendance`. */
export function absoluteUrl(path = "/"): string {
  return `${SITE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

/**
 * Metadata for one public page: its canonical URL plus matching Open Graph and
 * Twitter tags.
 *
 * Next.js replaces a parent's `openGraph` wholesale rather than merging it, so
 * each page has to carry the full set, hence this helper. The preview image comes
 * from the nearest `opengraph-image.tsx`, which Next adds on its own.
 */
export function pageMetadata({
  title,
  description,
  path,
}: {
  /** Omit to use the root layout's default title. */
  title?: string;
  description: string;
  path: string;
}): Metadata {
  const shareTitle = title ? `${title} · ${SITE_NAME}` : `${SITE_NAME}: ${SITE_TAGLINE}`;
  return {
    ...(title ? { title } : {}),
    description,
    alternates: { canonical: path },
    openGraph: {
      type: "website",
      siteName: SITE_NAME,
      url: path,
      title: shareTitle,
      description,
    },
    twitter: { card: "summary_large_image", title: shareTitle, description },
  };
}
