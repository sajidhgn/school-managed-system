import type { Locale } from "./config";

/**
 * Per-module translation catalogs.
 *
 * `messages.ts` holds the strings every screen shares (navigation, auth, common
 * buttons). Each module's own screens keep their strings beside the module, in
 * `lib/i18n/modules/<module>.ts`, so the fee screens and the attendance screens can
 * be translated — and changed — without both editing one 3,000-line file.
 *
 * The rule from `messages.ts` carries over: English is the source of truth and the
 * Urdu half must have exactly the same keys, so a missing translation is a TYPE
 * ERROR, never a string that silently renders in English for one user.
 *
 *   export const feesMessages = defineCatalog({
 *     en: { title: "Fees", challans: "{count} challans" },
 *     ur: { title: "فیس", challans: "{count} چالان" },
 *   });
 *
 * Read it with `useCatalog(feesMessages)` in a client component, or
 * `await getCatalog(feesMessages)` in a server component. Placeholders are filled
 * with `fill()` from `./format`, never by concatenation — word order differs.
 */

/** The same shape as `T`, every leaf a string. */
export type Translation<T> = {
  [K in keyof T]: T[K] extends string ? string : Translation<T[K]>;
};

export interface Catalog<T> {
  en: T;
  ur: Translation<T>;
}

export function defineCatalog<T extends Record<string, unknown>>(catalog: {
  en: T;
  ur: Translation<T>;
}): Catalog<T> {
  return catalog;
}

/** The strings for one locale. English is returned typed as its own translation. */
export function pickCatalog<T>(catalog: Catalog<T>, locale: Locale): Translation<T> {
  return locale === "ur" ? catalog.ur : (catalog.en as unknown as Translation<T>);
}
