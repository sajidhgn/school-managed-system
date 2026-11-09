"use client";

import * as React from "react";
import { Check, Loader2, Plus } from "lucide-react";

import { ErrorState } from "@/components/data-states";
import { Pagination } from "@/components/pagination";
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
import { fill } from "@/lib/i18n/format";
import { papersMessages } from "@/lib/i18n/modules/papers";
import { useCatalog } from "@/lib/i18n/use-catalog";
import {
  DIFFICULTY_VARIANT,
  QUESTION_DIFFICULTIES,
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
  const t = useCatalog(papersMessages);
  const m = t.bank;
  const add = useAddPaperQuestion(paper.id);
  const [type, setType] = React.useState<QuestionType | "">("");
  const [difficulty, setDifficulty] = React.useState<QuestionDifficulty | "">("");
  const [q, setQ] = React.useState("");
  const debounced = useDebouncedValue(q.trim(), 350);
  const [page, setPage] = React.useState(1);

  // Any filter change starts again at page 1, adjusted during render so the stale
  // page is never fetched against the new filters.
  const filterKey = `${type}|${difficulty}|${debounced}`;
  const [filteredBy, setFilteredBy] = React.useState(filterKey);
  if (filterKey !== filteredBy) {
    setFilteredBy(filterKey);
    setPage(1);
  }

  // The filters, the search and the page are applied by the API in the database.
  const bank = useQuestionBank(
    {
      class_id: paper.class_id,
      language: paper.language,
      type: type || null,
      difficulty: difficulty || null,
      q: debounced || null,
      page,
      size: 20,
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
          <DialogTitle>{m.title}</DialogTitle>
          <DialogDescription>
            {fill(m.description, {
              className: paper.class_name ?? m.thisClass,
              language: t.languageName[paper.language],
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-2 sm:grid-cols-[1fr_11rem_9rem]">
          <Input
            aria-label={m.searchAria}
            placeholder={m.searchPlaceholder}
            value={q}
            maxLength={200}
            onChange={(event) => setQ(event.target.value)}
          />
          <NativeSelect
            aria-label={m.typeAria}
            value={type}
            onChange={(event) => setType(event.target.value as QuestionType | "")}
          >
            <option value="">{m.allTypes}</option>
            {QUESTION_TYPE_ORDER.map((option) => (
              <option key={option} value={option}>
                {t.questionType[option]}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect
            aria-label={m.difficultyAria}
            value={difficulty}
            onChange={(event) => setDifficulty(event.target.value as QuestionDifficulty | "")}
          >
            <option value="">{m.anyDifficulty}</option>
            {QUESTION_DIFFICULTIES.map((d) => (
              <option key={d} value={d}>
                {t.difficulty[d]}
              </option>
            ))}
          </NativeSelect>
        </div>

        <div className="min-h-48">
          {bank.isLoading ? (
            <p className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> {m.loading}
            </p>
          ) : bank.isError ? (
            <ErrorState error={bank.error} onRetry={() => void bank.refetch()} className="py-8" />
          ) : !bank.data?.items.length ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              {debounced || type || difficulty ? m.noMatch : m.empty}
            </p>
          ) : (
            <>
              <ul className="space-y-2">
                {bank.data.items.map((question) => {
                  const already = onPaper.has(question.id);
                  const adding = add.isPending && add.variables?.question_id === question.id;
                  return (
                    <li
                      key={question.id}
                      className="flex items-start gap-3 rounded-lg border border-border p-3"
                    >
                      <div className="min-w-0 flex-1 space-y-2">
                        <div className="flex flex-wrap items-center gap-1.5 text-xs">
                          <Badge variant="outline">{t.questionType[question.type]}</Badge>
                          <Badge variant={DIFFICULTY_VARIANT[question.difficulty]}>
                            {t.difficulty[question.difficulty]}
                          </Badge>
                          <Badge variant="neutral">
                            {fill(question.marks === 1 ? t.question.marksOne : t.question.marksMany, {
                              count: question.marks,
                            })}
                          </Badge>
                          {question.chapter_number !== null && (
                            <span className="text-muted-foreground">
                              {question.printed_page !== null
                                ? fill(m.chapterPageRef, {
                                    number: question.chapter_number,
                                    page: question.printed_page,
                                  })
                                : fill(m.chapterRef, { number: question.chapter_number })}
                            </span>
                          )}
                          {!fits.has(question.type) && (
                            <span className="text-warning-foreground dark:text-warning">
                              {m.notUsual}
                            </span>
                          )}
                        </div>
                        <QuestionContent question={question} compact />
                      </div>
                      {already ? (
                        <Badge variant="success" className="mt-1 shrink-0 gap-1">
                          <Check className="size-3" /> {m.onPaper}
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
                          {!adding && <Plus />} {m.add}
                        </Button>
                      )}
                    </li>
                  );
                })}
              </ul>
              <Pagination meta={bank.data.meta} onPageChange={setPage} disabled={bank.isFetching} />
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
