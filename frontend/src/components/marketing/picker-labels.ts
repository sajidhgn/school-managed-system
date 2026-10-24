import type { Locale } from "@/lib/i18n/config";

/**
 * Words for the public site's language and theme pickers, in the page's
 * language only. The site's rule is that an English page carries no Urdu and an
 * Urdu page no English (copy.ts).
 *
 * Its own module, not copy.ts: the pickers are client components, and copy.ts
 * would bring every word of the site into the browser bundle with it.
 */

/**
 * Each language named in the page's language: "Urdu" on an English page,
 * "انگریزی" on an Urdu one. So the endonyms the panel's picker uses
 * (LOCALE_NAMES) are not used here.
 */
export const LANGUAGE_NAMES: Record<Locale, Record<Locale, string>> = {
  en: { en: "English", ur: "Urdu" },
  ur: { en: "انگریزی", ur: "اردو" },
};

/** The language picker's accessible name. */
export const LANGUAGE_LABEL: Record<Locale, string> = { en: "Language", ur: "زبان" };

/** The header's theme button, named for what pressing it does. */
export const THEME_LABELS: Record<Locale, { label: string; toLight: string; toDark: string }> = {
  en: { label: "Theme", toLight: "Switch to light theme", toDark: "Switch to dark theme" },
  ur: { label: "تھیم", toLight: "روشن تھیم پر جائیں", toDark: "تاریک تھیم پر جائیں" },
};
