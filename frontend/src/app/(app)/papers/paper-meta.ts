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

export const QUESTION_TYPE_LABELS: Record<QuestionType, string> = {
  mcq: "Multiple choice",
  true_false: "True / false",
  fill_blank: "Fill in the blank",
  short: "Short question",
  long: "Long question",
};

/** Section headings on screen; the printed paper has its own, in its language. */
export const SECTION_LABELS: Record<QuestionType, string> = {
  mcq: "Multiple choice",
  true_false: "True or false",
  fill_blank: "Fill in the blanks",
  short: "Short questions",
  long: "Long questions",
};

export const PAPER_TYPE_LABELS: Record<PaperType, string> = {
  objective: "Objective",
  subjective: "Subjective",
  mix: "Mix",
};

export const PAPER_TYPE_HINTS: Record<PaperType, string> = {
  objective: "MCQs, true/false and fill in the blanks",
  subjective: "Short and long questions",
  mix: "At least one objective and one subjective section",
};

export const PAPER_DIFFICULTY_LABELS: Record<PaperDifficulty, string> = {
  easy: "Easy",
  medium: "Medium",
  hard: "Hard",
  mixed: "Mixed",
};

export const DIFFICULTY_LABELS: Record<QuestionDifficulty, string> = {
  easy: "Easy",
  medium: "Medium",
  hard: "Hard",
};

export const DIFFICULTY_VARIANT: Record<QuestionDifficulty, BadgeProps["variant"]> = {
  easy: "success",
  medium: "default",
  hard: "warning",
};

export const LANGUAGE_LABELS: Record<PaperLanguage, string> = {
  en: "English",
  ur: "اردو",
  ar: "العربية",
};

/** The languages named in English, for sentences the screens say about a paper. */
export const LANGUAGE_NAMES: Record<PaperLanguage, string> = {
  en: "English",
  ur: "Urdu",
  ar: "Arabic",
};

export const PAPER_STATUS: Record<PaperStatus, { label: string; variant: BadgeProps["variant"] }> =
  {
    queued: { label: "Queued", variant: "default" },
    generating: { label: "Writing questions…", variant: "default" },
    ready: { label: "Ready", variant: "success" },
    needs_review: { label: "Needs review", variant: "warning" },
    failed: { label: "Failed", variant: "destructive" },
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

/** Everything wrong with the sections as entered, in words a teacher can act on. */
export function sectionProblems(paperType: PaperType, rows: SectionRow[]): string[] {
  const problems: string[] = [];
  if (!rows.length) return ["Add at least one section."];

  const allowed = new Set(TYPES_FOR_PAPER[paperType]);
  for (const row of rows) {
    const label = SECTION_LABELS[row.type];
    if (!allowed.has(row.type)) {
      problems.push(
        `${label} does not belong on a ${PAPER_TYPE_LABELS[paperType].toLowerCase()} paper.`,
      );
    }
    const count = Number(row.count);
    if (!Number.isInteger(count) || count < 1 || count > MAX_SECTION_COUNT) {
      problems.push(`${label}: the number of questions must be 1–${MAX_SECTION_COUNT}.`);
    }
    if (row.marks.trim()) {
      const marks = Number(row.marks);
      if (!Number.isInteger(marks) || marks < 1 || marks > MAX_MARKS) {
        problems.push(`${label}: marks per question must be 1–${MAX_MARKS}.`);
      }
    }
  }

  const types = rows.map((r) => r.type);
  if (new Set(types).size !== types.length) {
    problems.push("Each question type can have one section only.");
  }
  if (paperType === "mix" && !(types.some(isObjective) && types.some((t) => !isObjective(t)))) {
    problems.push("A mix paper needs at least one objective and one subjective section.");
  }
  const total = rows.reduce((sum, r) => sum + (Number(r.count) || 0), 0);
  if (total > MAX_QUESTIONS) {
    problems.push(`A paper holds at most ${MAX_QUESTIONS} questions — this one has ${total}.`);
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
