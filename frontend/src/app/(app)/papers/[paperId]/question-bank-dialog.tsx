"use client";

import * as React from "react";
import { Check, Loader2, Plus } from "lucide-react";

import { ErrorState } from "@/components/data-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useAddPaperQuestion, useQuestionBank } from "@/hooks/use-papers";
import type { PaperDetail, QuestionDifficulty, QuestionType } from "@/lib/api/types";
import {
  DIFFICULTY_LABELS,
  DIFFICULTY_VARIANT,
  LANGUAGE_NAMES,
  QUESTION_TYPE_LABELS,
  QUESTION_TYPE_ORDER,
  TYPES_FOR_PAPER,
} from "../paper-meta";
import { QuestionContent } from "./question-content";

/**
 * Put questions from the class's bank on the paper -- every question the agent has
 * written for this class in the paper's language, whether it made a paper or not.
 * A question joins the end of its type's section at its own marks.
 */
export function QuestionBankDialog({
  open,
  onOpenChange,
  paper,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  paper: PaperDetail;
}) {
  const add = useAddPaperQuestion(paper.id);
  const [type, setType] = React.useState<QuestionType | "">("");
  const [difficulty, setDifficulty] = React.useState<QuestionDifficulty | "">("");
  const [q, setQ] = React.useState("");
  const debounced = useDebouncedValue(q.trim(), 350);

  const bank = useQuestionBank(
    {
      class_id: paper.class_id,
      language: paper.language,
      type: type || null,
      difficulty: difficulty || null,
      q: debounced || null,
      limit: 50,
    },
    open,
  );

  const onPaper = React.useMemo(
    () => new Set(paper.sections.flatMap((s) => s.questions.map((e) => e.question.id))),
    [paper.sections],
  );
  const fits = new Set(TYPES_FOR_PAPER[paper.paper_type]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Add from question bank</DialogTitle>
          <DialogDescription>
            Questions written for {paper.class_name ?? "this class"} in{" "}
            {LANGUAGE_NAMES[paper.language]}, including ones removed or replaced on other papers.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-2 sm:grid-cols-[1fr_11rem_9rem]">
          <Input
            aria-label="Search questions"
            placeholder="Search the question text…"
            value={q}
            maxLength={200}
            onChange={(event) => setQ(event.target.value)}
          />
          <NativeSelect
            aria-label="Question type"
            value={type}
            onChange={(event) => setType(event.target.value as QuestionType | "")}
          >
            <option value="">All types</option>
            {QUESTION_TYPE_ORDER.map((t) => (
              <option key={t} value={t}>
                {QUESTION_TYPE_LABELS[t]}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect
            aria-label="Difficulty"
            value={difficulty}
            onChange={(event) => setDifficulty(event.target.value as QuestionDifficulty | "")}
          >
            <option value="">Any difficulty</option>
            {(["easy", "medium", "hard"] as const).map((d) => (
              <option key={d} value={d}>
                {DIFFICULTY_LABELS[d]}
              </option>
            ))}
          </NativeSelect>
        </div>

        <div className="min-h-48">
          {bank.isLoading ? (
            <p className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading questions…
            </p>
          ) : bank.isError ? (
            <ErrorState error={bank.error} onRetry={() => void bank.refetch()} className="py-8" />
          ) : !bank.data?.length ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              {debounced || type || difficulty
                ? "No question in the bank matches."
                : "The bank has no questions for this class in this language yet."}
            </p>
          ) : (
            <ul className="space-y-2">
              {bank.data.map((question) => {
                const already = onPaper.has(question.id);
                const adding = add.isPending && add.variables?.question_id === question.id;
                return (
                  <li
                    key={question.id}
                    className="flex items-start gap-3 rounded-lg border border-border p-3"
                  >
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex flex-wrap items-center gap-1.5 text-xs">
                        <Badge variant="outline">{QUESTION_TYPE_LABELS[question.type]}</Badge>
                        <Badge variant={DIFFICULTY_VARIANT[question.difficulty]}>
                          {DIFFICULTY_LABELS[question.difficulty]}
                        </Badge>
                        <Badge variant="neutral">
                          {question.marks} mark{question.marks === 1 ? "" : "s"}
                        </Badge>
                        {question.chapter_number !== null && (
                          <span className="text-muted-foreground">
                            Ch {question.chapter_number}
                            {question.printed_page !== null ? `, p. ${question.printed_page}` : ""}
                          </span>
                        )}
                        {!fits.has(question.type) && (
                          <span className="text-warning-foreground dark:text-warning">
                            not usually on this paper type
                          </span>
                        )}
                      </div>
                      <QuestionContent question={question} compact />
                    </div>
                    {already ? (
                      <Badge variant="success" className="mt-1 shrink-0 gap-1">
                        <Check className="size-3" /> On paper
                      </Badge>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        className="shrink-0"
                        loading={adding}
                        disabled={add.isPending && !adding}
                        onClick={() => add.mutate({ question_id: question.id })}
                      >
                        {!adding && <Plus />} Add
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
