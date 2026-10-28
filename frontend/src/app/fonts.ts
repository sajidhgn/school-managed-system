import { Noto_Sans_Arabic } from "next/font/google";

/**
 * The Urdu face, for every surface: the public site, the admin panel and the
 * operator console all draw Urdu in Noto Sans Arabic, from this one definition.
 *
 *   Noto Sans Arabic is a clean sans-serif Naskh with the full Urdu alphabet and
 *   every weight, so Urdu headings are as heavy as English ones and lines stay
 *   close to Latin height. (Nastaliq was used first on the public site; its tall
 *   calligraphy crowded headings and small labels. Printed test papers still use
 *   Nastaliq: app/(app)/papers/script-font.ts.)
 *
 * The root layout puts `variable` on <html>, so `--face-urdu` is defined on
 * `:root`, where globals.css builds the panel's stack and marketing.css the
 * public site's. With `preload: false` it downloads only once Urdu text renders
 * -- on an English page that is the language switcher's "اردو", one cached
 * Arabic-subset file.
 */
export const urduFace = Noto_Sans_Arabic({
  subsets: ["arabic"],
  weight: "variable",
  display: "swap",
  preload: false,
  variable: "--face-urdu",
});
