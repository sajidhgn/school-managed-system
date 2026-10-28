import { IBM_Plex_Mono, Kalam, Lexend, Plus_Jakarta_Sans } from "next/font/google";

/**
 * The public site's faces. Only the (marketing) layout imports this, so the tenant
 * panel and the operator console never download them.
 *
 *   Display  Plus Jakarta Sans: a geometric sans, set heavy and tight for
 *            headlines, numbers and the nav.
 *   Body     Lexend, drawn to make reading easier, which suits a product parents and
 *            teachers read on cheap phones. (Atkinson Hyperlegible was tried first;
 *            its slashed zero turned "50 students" into "5Ø".)
 *   Hand     Kalam: South Asian handwriting, used for the diary page and the margin
 *            notes. It plays the teacher's pen, so it stays out of body copy.
 *   Mono     IBM Plex Mono, for challan numbers and amounts.
 *   Urdu     Noto Sans Arabic -- not loaded here: the admin panel draws Urdu in
 *            the same face, so it is defined once in app/fonts.ts and the root
 *            layout sets `--face-urdu` on <html> for both.
 */
const display = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  display: "swap",
  variable: "--mk-face-display",
});

const body = Lexend({
  subsets: ["latin"],
  weight: ["400", "600"],
  display: "swap",
  variable: "--mk-face-body",
});

const hand = Kalam({
  subsets: ["latin"],
  weight: ["400", "700"],
  display: "swap",
  variable: "--mk-face-hand",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["500"],
  display: "swap",
  variable: "--mk-face-mono",
});

/**
 * Put on the layout's root. Each sets a raw face (`--mk-face-*`); marketing.css
 * builds the `--mk-font-*` stacks from them and the shared `--face-urdu`, Urdu
 * face first on Urdu pages, so every `font-mk-*` utility resolves in either
 * language.
 */
export const marketingFontVariables = [
  display.variable,
  body.variable,
  hand.variable,
  mono.variable,
].join(" ");
