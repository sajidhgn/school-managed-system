import { defineCatalog } from "../catalog";

/**
 * Global search strings not in `messages.ts` (`t.search.*` holds the rest):
 * `components/search/**`. Scope labels, group labels, the parsed-query summary and
 * warnings come from the server and are rendered as sent.
 */
export const searchMessages = defineCatalog({
  en: {
    resultCount: { one: "{count} result", other: "{count} results" },
  },
  ur: {
    resultCount: { one: "{count} نتیجہ", other: "{count} نتائج" },
  },
});
