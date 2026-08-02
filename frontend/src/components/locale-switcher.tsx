"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { useTranslations } from "@/components/providers/i18n-provider";
import { LOCALES, LOCALE_COOKIE, LOCALE_NAMES } from "@/lib/i18n/config";

/**
 * Language picker.
 *
 * Writes the locale cookie and calls `router.refresh()`, which re-runs the server
 * render — so `<html lang>` and `dir` update, and every server component picks up
 * the new catalog. A client-side state swap could not do that: the direction
 * attribute lives on the document element, above React's tree.
 *
 * The cookie is deliberately NOT httpOnly. It carries no authority — it selects a
 * language — and the switcher needs to write it without a round trip to a route
 * handler for what is a display preference.
 */
export function LocaleSwitcher() {
  const { locale } = useTranslations();
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function select(next: string) {
    // One year: a language choice is not a session, and re-asking every visit
    // would be the kind of small friction that makes a product feel careless.
    document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=${60 * 60 * 24 * 365}; samesite=lax`;
    startTransition(() => router.refresh());
  }

  return (
    <select
      aria-label="Language"
      value={locale}
      disabled={pending}
      onChange={(event) => select(event.target.value)}
      className="h-8 rounded-md border border-border bg-card px-2 text-sm text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
    >
      {LOCALES.map((code) => (
        <option key={code} value={code}>
          {LOCALE_NAMES[code]}
        </option>
      ))}
    </select>
  );
}
