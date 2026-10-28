import type { Metadata, Viewport } from "next";

import { I18nProvider } from "@/components/providers/i18n-provider";
import { Providers } from "@/components/providers";
import { directionFor } from "@/lib/i18n/config";
import { getMessages } from "@/lib/i18n/messages";
import { getLocale } from "@/lib/i18n/server";
import { SITE_NAME, SITE_TAGLINE, SITE_URL } from "@/lib/site";

import { urduFace } from "./fonts";
import "./globals.css";
import "./heroui.css";

export const metadata: Metadata = {
  // Resolves relative canonical and Open Graph URLs to absolute ones.
  metadataBase: new URL(SITE_URL),
  applicationName: SITE_NAME,
  title: {
    default: `${SITE_NAME}: ${SITE_TAGLINE}`,
    template: `%s · ${SITE_NAME}`,
  },
  description:
    "Fees and bank challans, attendance, exams and test papers from your own textbooks, plus a WhatsApp diary teachers send as a photo. Free for one school.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0b0d12" },
  ],
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const dir = directionFor(locale);
  const messages = getMessages(locale);

  return (
    // `lang` and `dir` are set from the resolved locale on every server render.
    //
    // `dir` is what makes RTL work at all: it flips the browser's own text
    // direction, and Tailwind's logical utilities (`ms-*`, `pe-*`, `text-start`)
    // resolve against it. Components therefore need no locale-aware styling —
    // which is the entire reason spec §9 asks for this on day one rather than as a
    // later "add Urdu" ticket.
    //
    // The Urdu face's variable goes on <html>, not <body>: globals.css composes the
    // panel's stack from it on `:root`, and a custom property only resolves
    // against variables defined on the same element or above.
    <html lang={locale} dir={dir} className={urduFace.variable} suppressHydrationWarning>
      <body className="min-h-svh bg-background font-sans antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:start-4 focus:top-4 focus:z-50 focus:rounded-control focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground"
        >
          Skip to content
        </a>
        <I18nProvider locale={locale} dir={dir} messages={messages}>
          <Providers>{children}</Providers>
        </I18nProvider>
      </body>
    </html>
  );
}
