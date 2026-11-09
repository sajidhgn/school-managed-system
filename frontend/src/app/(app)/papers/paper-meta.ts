import type { BadgeProps } from "@/components/ui/badge";
import type {
  PaperDifficulty,
  PaperLanguage,
  PaperSectionInput,
  PaperSectionRead,
  PaperStatus,
  PaperType,
  QuestionDifficulty,
  QuestionType,
} from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import type { PapersStrings } from "@/lib/i18n/modules/papers";

/**
 * The paper rules the backend enforces (backend/app/modules/papers/schemas.py),
 * repeated here so the form can say what is wrong before the request is sent. The
 * server stays the authority: a rule changed there and not here is a 422, not a
 * bad paper.
 */
export const MAX_QUESTIONS = 100;
export const MAX_SECTION_COUNT = 50;
export const MAX_MARKS = 100;
export const MAX_CHAPTERS = 20;

/** The order sections print in -- and the order the server returns them in. */
export const QUESTION_TYPE_ORDER: readonly QuestionType[] = [
  "mcq",
  "true_false",
  "fill_blank",
  "short",
  "long",
];

export const TYPES_FOR_PAPER: Record<PaperType, readonly QuestionType[]> = {
  objective: ["mcq", "true_false", "fill_blank"],
  subjective: ["short", "long"],
  mix: QUESTION_TYPE_ORDER,
};

const OBJECTIVE: ReadonlySet<QuestionType> = new Set(TYPES_FOR_PAPER.objective);

/** Marks per question when a section does not say otherwise. */
export const DEFAULT_MARKS: Record<QuestionType, number> = {
  mcq: 1,
  true_false: 1,
  fill_blank: 1,
  short: 2,
  long: 5,
};

/** What the form starts from when a paper type is picked; the teacher edits it. */
export const SECTION_PRESETS: Record<PaperType, PaperSectionInput[]> = {
  objective: [
    { type: "mcq", count: 10, marks: 1 },
    { type: "fill_blank", count: 5, marks: 1 },
  ],
  subjective: [
    { type: "short", count: 5, marks: 2 },
    { type: "long", count: 2, marks: 5 },
  ],
  mix: [
    { type: "mcq", count: 10, marks: 1 },
    { type: "short", count: 5, marks: 2 },
    { type: "long", count: 2, marks: 5 },
  ],
};

/*
 * The display labels for these enums -- question types, section headings, paper
 * types, difficulties, statuses -- are in the viewer's language, in
 * `lib/i18n/modules/papers.ts`; read them with `useCatalog(papersMessages)`.
 */

export const PAPER_DIFFICULTIES: readonly PaperDifficulty[] = ["easy", "medium", "hard", "mixed"];
export const QUESTION_DIFFICULTIES: readonly QuestionDifficulty[] = ["easy", "medium", "hard"];

export const DIFFICULTY_VARIANT: Record<QuestionDifficulty, BadgeProps["variant"]> = {
  easy: "success",
  medium: "default",
  hard: "warning",
};

/**
 * Each language named in itself -- the paper language picker and badges. Not
 * translated: like the app's own language switcher, a reader picks the language
 * they can read by its own name. (`languageName` in the catalog names them in the
 * viewer's language, for sentences.)
 */
export const LANGUAGE_LABELS: Record<PaperLanguage, string> = {
  en: "English",
  ur: "اردو",
  ar: "العربية",
};

/** Badge colour per status; the label is `status` in the papers catalog. */
export const PAPER_STATUS_VARIANT: Record<PaperStatus, BadgeProps["variant"]> = {
  queued: "default",
  generating: "default",
  ready: "success",
  needs_review: "warning",
  failed: "destructive",
};

export function isObjective(type: QuestionType): boolean {
  return OBJECTIVE.has(type);
}

export function sortSections(sections: PaperSectionRead[]): PaperSectionRead[] {
  return [...sections].sort(
    (a, b) => QUESTION_TYPE_ORDER.indexOf(a.type) - QUESTION_TYPE_ORDER.indexOf(b.type),
  );
}

/**
 * "10 × 1 = 10" when every question in the section carries the same marks, which
 * is the usual case; a section whose marks were edited one by one shows only its
 * total, because "10 × 1" would then be a lie.
 */
export function sectionMarks(section: PaperSectionRead): {
  count: number;
  each: number | null;
  total: number;
} {
  const marks = section.questions.map((q) => q.marks);
  const count = marks.length;
  const total = marks.reduce((sum, m) => sum + m, 0);
  const each = count && marks.every((m) => m === marks[0]) ? marks[0] : null;
  return { count, each, total };
}

/**
 * The direction a piece of question text reads in.
 *
 * NOT `dir="auto"`: that takes the FIRST strong character, so an Urdu question that
 * opens with a formula or an English term ("DNA کیا ہے؟") would be laid out
 * left-to-right with its question mark on the wrong side. Any Arabic-script letter
 * (Urdu or Arabic) makes the text right-to-left; text with Latin letters and none
 * is left-to-right (a formula on an Urdu or Arabic paper still reads correctly as
 * an isolated LTR run); text with neither -- digits and symbols -- follows the paper.
 */
const ARABIC_SCRIPT = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/;
const LATIN = /[A-Za-z]/;

export function textDir(text: string, fallback: PaperLanguage): "rtl" | "ltr" {
  if (ARABIC_SCRIPT.test(text)) return "rtl";
  if (LATIN.test(text)) return "ltr";
  return fallback === "en" ? "ltr" : "rtl";
}

export interface SectionRow {
  key: number;
  type: QuestionType;
  count: string;
  marks: string;
}

/**
 * Everything wrong with the sections as entered, in words a teacher can act on.
 * `t` is the papers catalog in the viewer's language.
 */
export function sectionProblems(
  paperType: PaperType,
  rows: SectionRow[],
  t: PapersStrings,
): string[] {
  const m = t.sectionProblems;
  const problems: string[] = [];
  if (!rows.length) return [m.none];

  const allowed = new Set(TYPES_FOR_PAPER[paperType]);
  for (const row of rows) {
    const section = t.section[row.type];
    if (!allowed.has(row.type)) {
      problems.push(
        fill(m.wrongType, { section, paperType: t.paperType[paperType].toLowerCase() }),
      );
    }
    const count = Number(row.count);
    if (!Number.isInteger(count) || count < 1 || count > MAX_SECTION_COUNT) {
      problems.push(fill(m.count, { section, max: MAX_SECTION_COUNT }));
    }
    if (row.marks.trim()) {
      const marks = Number(row.marks);
      if (!Number.isInteger(marks) || marks < 1 || marks > MAX_MARKS) {
        problems.push(fill(m.marks, { section, max: MAX_MARKS }));
      }
    }
  }

  const types = rows.map((r) => r.type);
  if (new Set(types).size !== types.length) {
    problems.push(m.duplicate);
  }
  if (paperType === "mix" && !(types.some(isObjective) && types.some((t) => !isObjective(t)))) {
    problems.push(m.mixNeedsBoth);
  }
  const total = rows.reduce((sum, r) => sum + (Number(r.count) || 0), 0);
  if (total > MAX_QUESTIONS) {
    problems.push(fill(m.tooMany, { max: MAX_QUESTIONS, total }));
  }
  return problems;
}

/** Option labels as printed: (a)–(d), (الف)–(د) in Urdu, (أ)–(د) in Arabic. */
const OPTION_LETTERS: Record<PaperLanguage, readonly string[]> = {
  en: ["a", "b", "c", "d"],
  ur: ["الف", "ب", "ج", "د"],
  ar: ["أ", "ب", "ج", "د"],
};

export function optionLabel(index: number, language: PaperLanguage): string {
  return `(${OPTION_LETTERS[language][index] ?? index + 1})`;
}

/** Section letters, A–E / الف–ہ / أ–هـ. Five question types means at most five sections. */
const SECTION_LETTERS: Record<PaperLanguage, readonly string[]> = {
  en: ["A", "B", "C", "D", "E"],
  ur: ["الف", "ب", "ج", "د", "ہ"],
  ar: ["أ", "ب", "ج", "د", "هـ"],
};

export function sectionLetter(index: number, language: PaperLanguage): string {
  return SECTION_LETTERS[language][index] ?? String(index + 1);
}

/** The agent's `report.issues`, read defensively -- `report` is free-form JSON. */
export function reportIssues(
  report: Record<string, unknown> | null,
): { code: string; message: string }[] {
  const issues = report?.issues;
  if (!Array.isArray(issues)) return [];
  return issues.filter(
    (issue): issue is { code: string; message: string } =>
      typeof issue === "object" && issue !== null && typeof issue.message === "string",
  );
}
