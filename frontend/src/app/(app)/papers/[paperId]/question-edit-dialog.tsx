"use client";

import * as React from "react";

import { Field } from "@/components/form/field";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { useUpdatePaperQuestion } from "@/hooks/use-papers";
import type { PaperQuestionRead, QuestionDifficulty, QuestionUpdate } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { papersMessages } from "@/lib/i18n/modules/papers";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { cn } from "@/lib/utils";
import { ChoiceGroup } from "../choice-group";
import { MAX_MARKS, QUESTION_DIFFICULTIES, optionLabel } from "../paper-meta";
import { isRtlLanguage } from "../script-font";

const EMPTY_OPTIONS = ["", "", "", ""];

/**
 * Edit one question on the paper, with the fields its type has: four options and
 * the correct one for an MCQ, the true/false choice, the answer key otherwise.
 *
 * The same rules as the server's (`INVALID_OPTIONS` / `INVALID_ANSWER`) are checked
 * here first so the teacher is told which field is wrong. The edit changes the
 * question in the bank too; a question another paper also uses is copied by the
 * server, so that paper keeps the old wording.
 */
export function QuestionEditDialog({
  open,
  onOpenChange,
  paperId,
  entry,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  paperId: string;
  entry: PaperQuestionRead;
}) {
  const t = useCatalog(papersMessages);
  const m = t.edit;
  const update = useUpdatePaperQuestion(paperId);
  const question = entry.question;
  const type = question.type;
  const language = question.language;
  const dir = isRtlLanguage(language) ? "rtl" : "ltr";

  const [text, setText] = React.useState("");
  const [options, setOptions] = React.useState<string[]>(EMPTY_OPTIONS);
  const [correct, setCorrect] = React.useState<number | null>(null);
  const [answer, setAnswer] = React.useState("");
  const [difficulty, setDifficulty] = React.useState<QuestionDifficulty>("medium");
  const [marks, setMarks] = React.useState("");
  const [attempted, setAttempted] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setText(question.text);
    setOptions(
      type === "mcq"
        ? [0, 1, 2, 3].map((i) => question.options?.[i] ?? "")
        : (question.options ?? EMPTY_OPTIONS),
    );
    setCorrect(question.correct_option);
    setAnswer(question.answer);
    setDifficulty(question.difficulty);
    setMarks(String(entry.marks));
    setAttempted(false);
  }, [open, question, type, entry.marks]);

  const errors: Record<string, string> = {};
  if (!text.trim()) errors.text = m.errors.text;
  if (type === "mcq") {
    const cleaned = options.map((o) => o.trim());
    if (cleaned.some((o) => !o)) errors.options = m.errors.optionsMissing;
    else if (new Set(cleaned.map((o) => o.toLowerCase())).size !== 4) {
      errors.options = m.errors.optionsSame;
    }
    if (correct === null || correct < 0 || correct > 3) errors.correct = m.errors.correct;
  } else if (type === "true_false") {
    if (correct !== 0 && correct !== 1) errors.correct = m.errors.trueFalse;
  } else if (!answer.trim()) {
    errors.answer = m.errors.answer;
  }
  const marksNumber = Number(marks);
  if (!Number.isInteger(marksNumber) || marksNumber < 1 || marksNumber > MAX_MARKS) {
    errors.marks = fill(m.errors.marks, { max: MAX_MARKS });
  }
  const show = (field: string) => (attempted ? errors[field] : undefined);
  const fieldError = (field: string) => (show(field) ? { message: show(field) } : undefined);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {fill(m.title, { type: t.questionType[type].toLowerCase() })}
          </DialogTitle>
          <DialogDescription>{m.description}</DialogDescription>
        </DialogHeader>
        <form
          id="question-edit-form"
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            setAttempted(true);
            if (Object.keys(errors).length) return;
            const body: QuestionUpdate = {
              text: text.trim(),
              answer: answer.trim(),
              difficulty,
              marks: marksNumber,
            };
            if (type === "mcq") {
              body.options = options.map((o) => o.trim());
              body.correct_option = correct;
            } else if (type === "true_false") {
              body.correct_option = correct;
            }
            update.mutate({ entryId: entry.id, body }, { onSuccess: () => onOpenChange(false) });
          }}
        >
          <Field label={m.question} htmlFor="question-text" error={fieldError("text")}>
            <Textarea
              dir={dir}
              lang={language}
              rows={3}
              maxLength={4000}
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
          </Field>

          {type === "mcq" && (
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">
                {m.options}{" "}
                <span className="font-normal text-muted-foreground">{m.optionsHint}</span>
              </legend>
              {options.map((option, index) => (
                <div key={index} className="flex items-center gap-2" dir={dir}>
                  <input
                    type="radio"
                    name="question-correct"
                    aria-label={fill(m.optionCorrectAria, { label: optionLabel(index, language) })}
                    checked={correct === index}
                    onChange={() => setCorrect(index)}
                  />
                  <span className="w-10 shrink-0 text-sm text-muted-foreground">
                    {optionLabel(index, language)}
                  </span>
                  <Input
                    aria-label={fill(m.optionAria, { label: optionLabel(index, language) })}
                    lang={language}
                    maxLength={500}
                    value={option}
                    className={cn(correct === index && "border-success")}
                    onChange={(event) =>
                      setOptions((current) =>
                        current.map((o, i) => (i === index ? event.target.value : o)),
                      )
                    }
                  />
                </div>
              ))}
              {(show("options") || show("correct")) && (
                <p className="text-sm text-destructive">{show("options") ?? show("correct")}</p>
              )}
            </fieldset>
          )}

          {type === "true_false" && (
            <div className="space-y-1.5">
              <ChoiceGroup
                label={m.correctAnswer}
                value={correct === null ? "" : String(correct)}
                onChange={(value) => setCorrect(Number(value))}
                options={options.slice(0, 2).map((option, index) => ({
                  value: String(index),
                  label: option || (index === 0 ? m.trueLabel : m.falseLabel),
                  lang: language,
                }))}
              />
              {show("correct") && <p className="text-sm text-destructive">{show("correct")}</p>}
            </div>
          )}

          <Field
            label={
              type === "mcq" || type === "true_false"
                ? m.explanation
                : type === "fill_blank"
                  ? m.fillAnswer
                  : m.answerKey
            }
            htmlFor="question-answer"
            error={fieldError("answer")}
          >
            <Textarea
              dir={dir}
              lang={language}
              rows={type === "long" ? 6 : 3}
              maxLength={8000}
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
            <ChoiceGroup
              label={m.difficulty}
              value={difficulty}
              onChange={setDifficulty}
              options={QUESTION_DIFFICULTIES.map((v) => ({
                value: v,
                label: t.difficulty[v],
              }))}
            />
            <Field label={m.marks} htmlFor="question-marks" error={fieldError("marks")}>
              <Input
                type="number"
                min={1}
                max={MAX_MARKS}
                value={marks}
                onChange={(event) => setMarks(event.target.value)}
              />
            </Field>
          </div>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={update.isPending}>
            {m.cancel}
          </Button>
          <Button type="submit" form="question-edit-form" loading={update.isPending}>
            {m.save}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
