"use client";

import * as React from "react";
import type { Route } from "next";
import Link from "next/link";
import { ArrowLeft, Loader2, Printer } from "lucide-react";

import { ErrorState, PageSpinner } from "@/components/data-states";
import { Button } from "@/components/ui/button";
import { BUSY_PAPER_STATUSES, usePaper } from "@/hooks/use-papers";
import type {
  PaperDetail,
  PaperLanguage,
  PaperQuestionRead,
  PaperSectionRead,
  QuestionType,
} from "@/lib/api/types";
import { cn } from "@/lib/utils";
import {
  isObjective,
  optionLabel,
  sectionLetter,
  sectionMarks,
  sortSections,
  textDir,
} from "../../paper-meta";
import { isRtlLanguage, rtlFace, rtlLanguage } from "../../script-font";
import { PaperText } from "../question-content";

/**
 * Everything the printed paper says that is not a question, in the paper's own
 * language -- an Urdu or Arabic paper is Urdu or Arabic from the masthead down,
 * whatever language the app itself is in. Numbers stay Western digits, as most
 * Urdu-medium schools print; Arabic uses Modern Standard Arabic exam wording.
 */
const TEXT: Record<
  PaperLanguage,
  {
    section: string;
    sections: Record<QuestionType, string>;
    className: string;
    subject: string;
    time: string;
    totalMarks: string;
    minutes: (n: number) => string;
    name: string;
    roll: string;
    instructions: string;
    answerKey: string;
  }
> = {
  en: {
    section: "Section",
    sections: {
      mcq: "Multiple choice",
      true_false: "True or false",
      fill_blank: "Fill in the blanks",
      short: "Short questions",
      long: "Long questions",
    },
    className: "Class",
    subject: "Subject",
    time: "Time allowed",
    totalMarks: "Total marks",
    minutes: (n) => `${n} minutes`,
    name: "Name",
    roll: "Roll No.",
    instructions: "Instructions",
    answerKey: "Answer key",
  },
  ur: {
    section: "حصہ",
    sections: {
      mcq: "کثیر الانتخابی سوالات",
      true_false: "درست/غلط",
      fill_blank: "خالی جگہ پُر کریں",
      short: "مختصر سوالات",
      long: "تفصیلی سوالات",
    },
    className: "جماعت",
    subject: "مضمون",
    time: "وقت",
    totalMarks: "کل نمبر",
    minutes: (n) => `${n} منٹ`,
    name: "نام",
    roll: "رول نمبر",
    instructions: "ہدایات",
    answerKey: "جوابات",
  },
  ar: {
    section: "القسم",
    sections: {
      mcq: "أسئلة الاختيار من متعدد",
      true_false: "صح أم خطأ",
      fill_blank: "املأ الفراغات",
      short: "أسئلة قصيرة",
      long: "أسئلة مقالية",
    },
    className: "الصف",
    subject: "المادة",
    time: "الزمن",
    totalMarks: "الدرجة الكلية",
    minutes: (n) => `${n} دقيقة`,
    name: "الاسم",
    roll: "رقم الجلوس",
    instructions: "التعليمات",
    answerKey: "نموذج الإجابة",
  },
};

/** Ruled answer lines under a written question. */
const ANSWER_LINES: Partial<Record<QuestionType, number>> = {
  short: 3,
  long: 9,
};

/**
 * The app chrome is the (app) layout's, which a nested page cannot opt out of -- so
 * the print stylesheet removes it instead: the sidebar, the header and banner beside
 * `#main`, and the toolbar. What is left is the sheet, on A4, black on white.
 */
function PrintStyle() {
  return (
    <style>{`
      @media print {
        @page { size: A4; margin: 14mm 15mm; }
        html, body { background: #fff !important; }
        body aside,
        div:has(> #main) > :not(#main) { display: none !important; }
        #main { padding: 0 !important; }
        /* The shell's flex columns, as plain blocks: page breaks inside flex items
           are not honoured everywhere, and the answer key must start a new page. */
        div:has(> #main), div:has(> div > #main) { display: block !important; }
        .exam-sheet {
          max-width: none !important;
          margin: 0 !important;
          padding: 0 !important;
          border: 0 !important;
          box-shadow: none !important;
        }
      }
    `}</style>
  );
}

export function PaperPrintView({
  paperId,
  schoolName,
}: {
  paperId: string;
  schoolName: string | null;
}) {
  const paper = usePaper(paperId);
  const [withKey, setWithKey] = React.useState(false);
  const [withLines, setWithLines] = React.useState(true);

  if (paper.isLoading) return <PageSpinner />;
  if (paper.isError || !paper.data) {
    return <ErrorState error={paper.error} onRetry={() => void paper.refetch()} />;
  }
  const data = paper.data;
  const busy = BUSY_PAPER_STATUSES.has(data.status);
  const sections = sortSections(data.sections).filter((s) => s.questions.length > 0);

  return (
    <div className="space-y-4">
      <PrintStyle />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 print:hidden">
        <Link
          href={`/papers/${data.id}` as Route}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back to the paper
        </Link>
        <div className="ms-auto flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={withLines}
              onChange={(event) => setWithLines(event.target.checked)}
            />
            Answer lines
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={withKey}
              onChange={(event) => setWithKey(event.target.checked)}
            />
            Answer key
          </label>
          <Button
            disabled={busy || !sections.length}
            onClick={async () => {
              // The Nastaliq face loads on first use; printing before it lands would
              // print the fallback font.
              await document.fonts?.ready;
              window.print();
            }}
          >
            <Printer /> Print
          </Button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground print:hidden">
        To get a PDF, choose &ldquo;Save as PDF&rdquo; as the printer. Turn off the browser&apos;s
        headers and footers in the print dialog for a clean page.
      </p>

      {busy ? (
        <p className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> The questions are still being written. This
          page updates by itself.
        </p>
      ) : !sections.length ? (
        <p className="py-16 text-center text-sm text-muted-foreground">
          This paper has no questions to print.
        </p>
      ) : (
        <>
          <Sheet paper={data}>
            <Masthead paper={data} schoolName={schoolName} />
            {sections.map((section, index) => (
              <PrintSection
                key={section.type}
                paper={data}
                section={section}
                index={index}
                withLines={withLines}
              />
            ))}
          </Sheet>
          {withKey && (
            <Sheet paper={data} className="break-before-page">
              <AnswerKey paper={data} sections={sections} />
            </Sheet>
          )}
        </>
      )}
    </div>
  );
}

/** One A4 page's worth of paper on screen; in print, just the content. */
function Sheet({
  paper,
  className,
  children,
}: {
  paper: PaperDetail;
  className?: string;
  children: React.ReactNode;
}) {
  const rtl = isRtlLanguage(paper.language);
  const face = rtlFace(paper.language);
  return (
    <article
      dir={rtl ? "rtl" : "ltr"}
      lang={paper.language}
      className={cn(
        "exam-sheet mx-auto w-full max-w-[210mm] space-y-5 border border-border bg-white p-6 text-[15px] text-black shadow-sm sm:p-[14mm]",
        rtl && face.className,
        className,
      )}
      style={{ lineHeight: rtl ? face.leading : 1.5 }}
    >
      {children}
    </article>
  );
}

/** A label and a ruled blank, filled with a value or left for the student. */
function Blank({
  label,
  value,
  className,
}: {
  label: string;
  value?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 items-baseline gap-2", className)}>
      <span className="shrink-0 font-semibold">{label}:</span>
      <span className="min-h-[1.5em] min-w-0 flex-1 border-b border-dotted border-black px-1">
        {value ? <bdi>{value}</bdi> : null}
      </span>
    </div>
  );
}

function Masthead({ paper, schoolName }: { paper: PaperDetail; schoolName: string | null }) {
  const t = TEXT[paper.language];
  return (
    <header className="space-y-3">
      <div className="space-y-1 text-center">
        {schoolName ? (
          <p className="text-lg font-bold uppercase tracking-wide">
            <bdi>{schoolName}</bdi>
          </p>
        ) : null}
        <h1 className="text-xl font-bold">
          <PaperText text={paper.title} language={paper.language} />
        </h1>
      </div>
      <div className="grid grid-cols-2 gap-x-8 gap-y-2">
        <Blank label={t.className} value={paper.class_name} />
        <Blank label={t.subject} value={paper.subject_name} />
        <Blank
          label={t.time}
          value={paper.duration_minutes ? t.minutes(paper.duration_minutes) : null}
        />
        <Blank label={t.totalMarks} value={String(paper.total_marks)} />
        <Blank label={t.name} />
        <Blank label={t.roll} />
      </div>
      {paper.instructions ? (
        <div className="border-y border-black py-2">
          <span className="font-semibold">{t.instructions}: </span>
          <span className="whitespace-pre-line">
            <PaperText text={paper.instructions} language={paper.language} />
          </span>
        </div>
      ) : (
        <hr className="border-black" />
      )}
    </header>
  );
}

function SectionHeading({
  paper,
  section,
  index,
}: {
  paper: PaperDetail;
  section: PaperSectionRead;
  index: number;
}) {
  const t = TEXT[paper.language];
  const { count, each, total } = sectionMarks(section);
  return (
    <h2 className="break-after-avoid font-bold">
      {t.section} {sectionLetter(index, paper.language)} — {t.sections[section.type]}{" "}
      {/* An LTR island: inside RTL text the bidi algorithm would otherwise lay the
          sum out backwards ("10 = 1 × 10"). */}
      <bdi dir="ltr">({each !== null ? `${count} × ${each} = ${total}` : total})</bdi>
    </h2>
  );
}

function PrintSection({
  paper,
  section,
  index,
  withLines,
}: {
  paper: PaperDetail;
  section: PaperSectionRead;
  index: number;
  withLines: boolean;
}) {
  const { each } = sectionMarks(section);
  const questions = [...section.questions].sort((a, b) => a.position - b.position);
  // Per-question marks are printed beside written questions, and beside any
  // question in a section whose marks were edited unevenly.
  const showMarks = each === null || !isObjective(section.type);

  return (
    <section className="space-y-3">
      <SectionHeading paper={paper} section={section} index={index} />
      <ol className="space-y-3">
        {questions.map((entry, i) => (
          <PrintQuestion
            key={entry.id}
            entry={entry}
            number={i + 1}
            showMarks={showMarks}
            withLines={withLines}
          />
        ))}
      </ol>
    </section>
  );
}

function PrintQuestion({
  entry,
  number,
  showMarks,
  withLines,
}: {
  entry: PaperQuestionRead;
  number: number;
  showMarks: boolean;
  withLines: boolean;
}) {
  const question = entry.question;
  const language = question.language;
  const lines = withLines ? (ANSWER_LINES[question.type] ?? 0) : 0;

  return (
    <li className="break-inside-avoid space-y-1.5">
      <div className="flex items-start gap-2">
        <span className="w-7 shrink-0 font-semibold">{number}.</span>
        <div className="min-w-0 flex-1 whitespace-pre-line">
          {question.type === "fill_blank" ? (
            <FillBlank text={question.text} language={language} />
          ) : (
            <PaperText text={question.text} language={language} />
          )}
        </div>
        {showMarks && (
          <span className="shrink-0 ps-2">
            <bdi dir="ltr">({entry.marks})</bdi>
          </span>
        )}
      </div>

      {question.options && question.options.length > 0 && (
        <div
          className={cn(
            "ms-9 grid gap-x-8 gap-y-1",
            question.type === "true_false" ? "grid-cols-[auto_auto] justify-start" : "grid-cols-2",
          )}
        >
          {question.options.map((option, index) => (
            <div key={index} className="flex min-w-0 items-baseline gap-2">
              <span className="shrink-0">{optionLabel(index, language)}</span>
              <PaperText text={option} language={language} className="min-w-0" />
            </div>
          ))}
        </div>
      )}

      {lines > 0 && (
        <div className="ms-9" aria-hidden>
          {Array.from({ length: lines }, (_, i) => (
            <div
              key={i}
              className="border-b border-dotted border-black/70"
              // Taller for Nastaliq, whose letters climb above the line.
              style={{
                height: language === "ur" ? "11mm" : language === "ar" ? "10mm" : "9mm",
              }}
            />
          ))}
        </div>
      )}
    </li>
  );
}

/**
 * A fill-in question with its "______" drawn as a ruled blank. The agent writes
 * exactly one; a question that came back without one gets a blank at the end, so
 * the student always has somewhere to write.
 */
function FillBlank({ text, language }: { text: string; language: PaperLanguage }) {
  const parts = text.split(/(_{3,})/);
  const hasBlank = parts.length > 1;
  const blank = (key: React.Key) => (
    <span key={key} className="mx-1 inline-block w-[30mm] border-b border-black align-baseline">
      &nbsp;
    </span>
  );
  const dir = textDir(text, language);
  return (
    <span dir={dir} lang={dir === "rtl" ? rtlLanguage(language) : "en"}>
      {parts.map((part, i) => (/^_{3,}$/.test(part) ? blank(i) : part))}
      {hasBlank ? null : blank("end")}
    </span>
  );
}

/** The key, after a page break: what a marker needs and nothing a student does. */
function AnswerKey({ paper, sections }: { paper: PaperDetail; sections: PaperSectionRead[] }) {
  const t = TEXT[paper.language];
  return (
    <>
      <h1 className="text-center text-xl font-bold">
        {t.answerKey} — <PaperText text={paper.title} language={paper.language} />
      </h1>
      {sections.map((section, index) => {
        const questions = [...section.questions].sort((a, b) => a.position - b.position);
        const objective = isObjective(section.type);
        return (
          <section key={section.type} className="space-y-2">
            <SectionHeading paper={paper} section={section} index={index} />
            <ol className={cn(objective ? "grid grid-cols-2 gap-x-8 gap-y-1" : "space-y-3")}>
              {questions.map((entry, i) => {
                const q = entry.question;
                const option =
                  q.options && q.correct_option !== null ? q.options[q.correct_option] : null;
                return (
                  <li key={entry.id} className="flex items-start gap-2 break-inside-avoid">
                    <span className="w-7 shrink-0 font-semibold">{i + 1}.</span>
                    <div className="min-w-0 flex-1 whitespace-pre-line">
                      {option !== null && q.correct_option !== null ? (
                        <>
                          <span className="font-semibold">
                            {optionLabel(q.correct_option, q.language)}
                          </span>{" "}
                          <PaperText text={option} language={q.language} />
                        </>
                      ) : (
                        <PaperText text={q.answer || "—"} language={q.language} />
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>
        );
      })}
    </>
  );
}
