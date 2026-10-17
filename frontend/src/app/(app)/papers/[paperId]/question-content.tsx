import { Check } from "lucide-react";

import type { PaperLanguage, QuestionRead } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { optionLabel, textDir } from "../paper-meta";
import { isRtlLanguage, rtlFace, rtlLanguage } from "../script-font";

/**
 * Text that may be English, Urdu or Arabic, in its own direction and -- for Urdu
 * and Arabic -- in that script's face (Nastaliq, Naskh). A `<span dir>` isolates
 * the run, so a formula inside an Urdu or Arabic sentence, or a whole English
 * option on such a paper, keeps its punctuation where it was written.
 */
export function PaperText({
  text,
  language,
  className,
}: {
  text: string;
  language: PaperLanguage;
  className?: string;
}) {
  const dir = textDir(text, language);
  const face = rtlFace(language);
  return (
    <span
      dir={dir}
      lang={dir === "rtl" ? rtlLanguage(language) : "en"}
      className={cn(dir === "rtl" && face.className, className)}
      style={dir === "rtl" ? { lineHeight: face.leading } : undefined}
    >
      {text}
    </span>
  );
}

/**
 * A question as the review screen shows it: the text, and for MCQ and true/false
 * the options with the correct one marked -- in words and a tick as well as colour.
 */
export function QuestionContent({
  question,
  showAnswer = true,
  compact = false,
}: {
  question: QuestionRead;
  showAnswer?: boolean;
  compact?: boolean;
}) {
  const language = question.language;
  const rtl = isRtlLanguage(language);
  return (
    <div className="space-y-2" dir={rtl ? "rtl" : "ltr"}>
      <p className={cn("whitespace-pre-line", compact ? "line-clamp-3 text-sm" : "text-[0.95rem]")}>
        <PaperText text={question.text} language={language} />
      </p>
      {question.options && question.options.length > 0 && (
        <ul
          className={cn(
            "grid gap-1.5 text-sm",
            question.type === "mcq" && !compact && "sm:grid-cols-2",
            question.type === "true_false" && "grid-cols-2 sm:max-w-sm",
          )}
        >
          {question.options.map((option, index) => {
            const correct = showAnswer && index === question.correct_option;
            return (
              <li
                key={index}
                className={cn(
                  "flex items-baseline gap-2 rounded-md border px-2.5 py-1.5",
                  correct ? "border-success/50 bg-success/10 font-medium" : "border-border",
                )}
              >
                <span className="shrink-0 text-muted-foreground">
                  {optionLabel(index, language)}
                </span>
                <PaperText text={option} language={language} className="min-w-0 flex-1" />
                {correct && (
                  <Check
                    className="size-4 shrink-0 self-center text-success"
                    aria-label="Correct answer"
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
