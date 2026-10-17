import { Noto_Naskh_Arabic, Noto_Nastaliq_Urdu } from "next/font/google";

import type { PaperLanguage } from "@/lib/api/types";

/**
 * The faces right-to-left papers print in. Only the papers pages import this, and
 * with `preload: false` a paper only downloads the face its language uses.
 *
 *   Urdu    Nastaliq -- the script Urdu is printed in at school. The system
 *           fallback is usually Naskh, which a child reads as Arabic.
 *   Arabic  Naskh -- the script Arabic textbooks are printed in.
 *
 * Nastaliq is TALL: its letters climb diagonally, so Urdu text needs a
 * line-height around 2.2 or the lines collide. Naskh needs less.
 */
const nastaliq = Noto_Nastaliq_Urdu({
  subsets: ["arabic"],
  weight: ["400", "700"],
  display: "swap",
  preload: false,
});

const naskh = Noto_Naskh_Arabic({
  subsets: ["arabic"],
  weight: ["400", "700"],
  display: "swap",
  preload: false,
});

type RtlLanguage = Exclude<PaperLanguage, "en">;

const FACES: Record<RtlLanguage, { className: string; leading: number }> = {
  ur: { className: nastaliq.className, leading: 2.2 },
  ar: { className: naskh.className, leading: 1.9 },
};

export function isRtlLanguage(language: PaperLanguage): language is RtlLanguage {
  return language !== "en";
}

/**
 * The language right-to-left text on a paper is in: the paper's own when it is
 * Urdu or Arabic. Arabic-script text on an English paper is taken as Urdu, the
 * likelier of the two in a Pakistani school.
 */
export function rtlLanguage(language: PaperLanguage): RtlLanguage {
  return isRtlLanguage(language) ? language : "ur";
}

/** The face and line-height for right-to-left text on a paper in `language`. */
export function rtlFace(language: PaperLanguage): {
  className: string;
  leading: number;
} {
  return FACES[rtlLanguage(language)];
}
