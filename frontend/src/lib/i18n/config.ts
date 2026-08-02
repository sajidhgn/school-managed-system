/**
 * Locale configuration (spec §9).
 *
 * =============================================================================
 * WHY THIS EXISTS ON DAY ONE RATHER THAN "WHEN WE LOCALISE"
 * =============================================================================
 *   Spec §9: "i18n scaffolded from day one (`en`, `ur`) with RTL support wired in
 *   Tailwind. Retrofitting RTL later costs 3× more than doing it now."
 *
 *   The expensive part is never the translation files. It is that a codebase written
 *   without RTL in mind accumulates thousands of directional assumptions — `ml-4`,
 *   `text-left`, `border-r`, `left-0` — and every one has to be found and converted.
 *   Wiring `dir` and using logical properties from the start makes that cost zero.
 *
 *   Urdu is the second locale because the target market is Pakistan, and Urdu is
 *   right-to-left. Picking an LTR second language would have proved nothing.
 */

export const LOCALES = ["en", "ur"] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "en";

/** Locales that render right-to-left. Drives the `dir` attribute on <html>. */
const RTL_LOCALES = new Set<Locale>(["ur"]);

export function isRtl(locale: Locale): boolean {
  return RTL_LOCALES.has(locale);
}

export function directionFor(locale: Locale): "ltr" | "rtl" {
  return isRtl(locale) ? "rtl" : "ltr";
}

export const LOCALE_NAMES: Record<Locale, string> = {
  en: "English",
  // Endonym, not "Urdu": a language picker that names languages in a language the
  // reader may not have is a picker they cannot use.
  ur: "اردو",
};

export function isLocale(value: string | undefined | null): value is Locale {
  return !!value && (LOCALES as readonly string[]).includes(value);
}

/** Cookie the locale switcher writes; read on every server render. */
export const LOCALE_COOKIE = "educloud_locale";
