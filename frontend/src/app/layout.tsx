import type { Metadata, Viewport } from "next";

import { I18nProvider } from "@/components/providers/i18n-provider";
import { Providers } from "@/components/providers";
import { directionFor } from "@/lib/i18n/config";
import { getMessages } from "@/lib/i18n/messages";
import { getLocale } from "@/lib/i18n/server";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "EduCloud — School management for growing groups",
    template: "%s · EduCloud",
  },
  description:
    "Multi-tenant school management: students, staff, roles, invitations and billing across every campus.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#15171f" },
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
    <html lang={locale} dir={dir} suppressHydrationWarning>
      <body className="min-h-svh bg-background font-sans antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:start-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground"
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
