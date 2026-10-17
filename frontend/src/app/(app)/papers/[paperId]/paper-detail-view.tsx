"use client";

import * as React from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  FileQuestion,
  Library,
  Loader2,
  Pencil,
  Printer,
  RotateCw,
  Shuffle,
  Trash2,
} from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState, ErrorState, PageSpinner } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  BUSY_PAPER_STATUSES,
  useDeletePaper,
  usePaper,
  useRegeneratePaper,
  useRemovePaperQuestion,
  useReplacePaperQuestion,
} from "@/hooks/use-papers";
import type {
  PaperDetail,
  PaperQuestionRead,
  PaperSectionRead,
  QuestionDifficulty,
} from "@/lib/api/types";
import { cn, formatDateTime } from "@/lib/utils";
import { ChoiceGroup } from "../choice-group";
import {
  DIFFICULTY_LABELS,
  DIFFICULTY_VARIANT,
  LANGUAGE_LABELS,
  PAPER_DIFFICULTY_LABELS,
  PAPER_STATUS,
  PAPER_TYPE_LABELS,
  SECTION_LABELS,
  optionLabel,
  reportIssues,
  sectionLetter,
  sectionMarks,
  sortSections,
} from "../paper-meta";
import { PaperDetailsDialog } from "./paper-details-dialog";
import { QuestionBankDialog } from "./question-bank-dialog";
import { PaperText, QuestionContent } from "./question-content";
import { QuestionEditDialog } from "./question-edit-dialog";

export function PaperDetailView({ paperId }: { paperId: string }) {
  const router = useRouter();
  const paper = usePaper(paperId);
  const removePaper = useDeletePaper();
  const regenerate = useRegeneratePaper(paperId);
  const [editing, setEditing] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [regenerating, setRegenerating] = React.useState(false);
  const [bankOpen, setBankOpen] = React.useState(false);

  if (paper.isLoading) return <PageSpinner />;
  if (paper.isError || !paper.data) {
    return <ErrorState error={paper.error} onRetry={() => void paper.refetch()} />;
  }
  const data = paper.data;
  const busy = BUSY_PAPER_STATUSES.has(data.status);
  // The API answers 409 PAPER_BUSY to any edit while the agent holds the paper.
  const editable = data.can_edit && !busy;
  const sections = sortSections(data.sections).filter((s) => s.questions.length > 0);
  const printable = !busy && data.question_count > 0;

  return (
    <div className="space-y-6">
      <Link
        href={"/papers" as Route}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" /> All test papers
      </Link>
      <PageHeader
        title={data.title}
        description={[data.class_name, data.subject_name, data.book_title]
          .filter(Boolean)
          .join(" · ")}
        actions={
          <>
            {printable ? (
              <Button asChild>
                <Link href={`/papers/${data.id}/print` as Route}>
                  <Printer /> Print
                </Link>
              </Button>
            ) : (
              <Button disabled>
                <Printer /> Print
              </Button>
            )}
            {editable && (
              <>
                <Button variant="outline" onClick={() => setEditing(true)}>
                  <Pencil /> Edit details
                </Button>
                <Button variant="outline" onClick={() => setRegenerating(true)}>
                  <RotateCw /> Regenerate
                </Button>
              </>
            )}
            {data.can_edit && (
              <Button
                variant="outline"
                size="icon"
                aria-label="Delete paper"
                onClick={() => setDeleting(true)}
              >
                <Trash2 />
              </Button>
            )}
          </>
        }
      />

      <SummaryCard paper={data} />

      {busy && (
        <Note icon={Loader2} spin>
          <span className="font-medium">Generating questions…</span> The agent is writing{" "}
          {data.requested.reduce((sum, s) => sum + s.count, 0)} questions from{" "}
          {data.chapters.length === 1 ? "the chapter" : `${data.chapters.length} chapters`} and
          checking each one against the book. This page updates by itself.
        </Note>
      )}
      {data.status === "failed" && (
        <Note icon={AlertTriangle} tone="destructive">
          {data.error ?? "The agent could not write this paper."}
          {data.can_edit ? " Regenerate to try again, or change the chapters in a new paper." : ""}
        </Note>
      )}
      {data.status === "needs_review" && <IssuesNote paper={data} />}

      {!busy && (
        <section className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-base font-semibold">
              Questions{" "}
              <span className="font-normal text-muted-foreground">
                ({data.question_count} · {data.total_marks} marks)
              </span>
            </h2>
            {editable && (
              <Button variant="outline" size="sm" onClick={() => setBankOpen(true)}>
                <Library /> Add from question bank
              </Button>
            )}
          </div>
          {sections.length ? (
            sections.map((section, index) => (
              <SectionCard
                key={section.type}
                paper={data}
                section={section}
                index={index}
                editable={editable}
              />
            ))
          ) : (
            <Card>
              <EmptyState
                icon={FileQuestion}
                title="No questions on this paper"
                description={
                  editable
                    ? "Regenerate the paper, or add questions from the class's question bank."
                    : undefined
                }
              />
            </Card>
          )}
        </section>
      )}

      <PaperDetailsDialog open={editing} onOpenChange={setEditing} paper={data} />
      <QuestionBankDialog open={bankOpen} onOpenChange={setBankOpen} paper={data} />
      <ConfirmDialog
        open={regenerating}
        onOpenChange={setRegenerating}
        title="Regenerate this paper?"
        description="The agent writes a new set of questions from the same chapters and settings. The current questions leave this paper but stay in the question bank, and any edits you made to them stay there too."
        confirmLabel="Regenerate"
        variant="default"
        loading={regenerate.isPending}
        onConfirm={() =>
          regenerate.mutate(undefined, {
            onSuccess: () => setRegenerating(false),
          })
        }
      />
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete ${data.title}?`}
        description="The paper is removed. Its questions stay in the class's question bank."
        confirmLabel="Delete paper"
        loading={removePaper.isPending}
        onConfirm={() =>
          removePaper.mutate(data.id, {
            onSuccess: () => router.push("/papers" as Route),
          })
        }
      />
    </div>
  );
}

function SummaryCard({ paper }: { paper: PaperDetail }) {
  const status = PAPER_STATUS[paper.status];
  const facts: [string, React.ReactNode][] = [
    [
      "Status",
      <Badge key="status" variant={status.variant} className="gap-1">
        {BUSY_PAPER_STATUSES.has(paper.status) && <Loader2 className="size-3 animate-spin" />}
        {status.label}
      </Badge>,
    ],
    [
      "Language",
      <span key="lang" lang={paper.language}>
        {LANGUAGE_LABELS[paper.language]}
      </span>,
    ],
    ["Paper type", PAPER_TYPE_LABELS[paper.paper_type]],
    ["Difficulty", PAPER_DIFFICULTY_LABELS[paper.difficulty]],
    ["Time allowed", paper.duration_minutes ? `${paper.duration_minutes} minutes` : "—"],
    ["Total marks", `${paper.total_marks} (${paper.question_count} questions)`],
  ];

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-3 lg:grid-cols-6">
          {facts.map(([label, value]) => (
            <div key={label} className="space-y-1">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="text-sm font-medium">{value}</dd>
            </div>
          ))}
        </dl>
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">
            Chapters{paper.book_title ? ` of ${paper.book_title}` : ""}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {paper.chapters.length ? (
              paper.chapters.map((chapter) => (
                <Badge key={chapter.id} variant="outline">
                  Ch {chapter.number}: {chapter.title}
                </Badge>
              ))
            ) : (
              <span className="text-sm text-muted-foreground">
                The chapters were removed from the book.
              </span>
            )}
          </div>
        </div>
        {paper.instructions ? (
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Instructions</p>
            <p className="whitespace-pre-line text-sm">
              <PaperText text={paper.instructions} language={paper.language} />
            </p>
          </div>
        ) : null}
        <p className="text-xs text-muted-foreground">
          Created {formatDateTime(paper.created_at)}
          {paper.created_by_name ? ` by ${paper.created_by_name}` : ""}
          {paper.generated_at ? ` · questions written ${formatDateTime(paper.generated_at)}` : ""}
        </p>
      </CardContent>
    </Card>
  );
}

function IssuesNote({ paper }: { paper: PaperDetail }) {
  const issues = reportIssues(paper.report);
  return (
    <div className="space-y-2 rounded-lg border border-warning/50 bg-warning/10 p-3 text-sm">
      <p className="flex items-center gap-2 font-medium">
        <Bot className="size-4" /> The agent asks you to review this paper
      </p>
      {issues.length ? (
        <ul className="space-y-1">
          {issues.map((issue, index) => (
            <li key={`${issue.code}-${index}`} className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" />
              <span>{issue.message}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground">
          Some questions did not come out as asked. Check them before printing.
        </p>
      )}
    </div>
  );
}

function SectionCard({
  paper,
  section,
  index,
  editable,
}: {
  paper: PaperDetail;
  section: PaperSectionRead;
  index: number;
  editable: boolean;
}) {
  const { count, each, total } = sectionMarks(section);
  const questions = [...section.questions].sort((a, b) => a.position - b.position);
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-baseline justify-between gap-2 pb-3">
        <CardTitle>
          Section {sectionLetter(index, "en")} — {SECTION_LABELS[section.type]}
        </CardTitle>
        <span className="text-sm text-muted-foreground tabular-nums">
          {each !== null
            ? `${count} × ${each} = ${total} marks`
            : `${count} questions · ${total} marks`}
        </span>
      </CardHeader>
      <CardContent>
        <ol className="space-y-3">
          {questions.map((entry, i) => (
            <QuestionItem
              key={entry.id}
              paper={paper}
              entry={entry}
              number={i + 1}
              editable={editable}
            />
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

function QuestionItem({
  paper,
  entry,
  number,
  editable,
}: {
  paper: PaperDetail;
  entry: PaperQuestionRead;
  number: number;
  editable: boolean;
}) {
  const replace = useReplacePaperQuestion(paper.id);
  const remove = useRemovePaperQuestion(paper.id);
  const [editing, setEditing] = React.useState(false);
  const [replacing, setReplacing] = React.useState(false);
  const [removing, setRemoving] = React.useState(false);

  const question = entry.question;
  const askedOther =
    entry.requested_difficulty !== null && entry.requested_difficulty !== question.difficulty;
  const optionDisagrees = question.checks?.option_agrees === false;
  const keyText =
    question.options && question.correct_option !== null
      ? `${optionLabel(question.correct_option, question.language)} ${question.options[question.correct_option] ?? ""}`
      : null;

  return (
    <li className="relative rounded-lg border border-border p-4">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 w-6 shrink-0 text-sm font-semibold tabular-nums">{number}.</span>
        <div className="min-w-0 flex-1 space-y-3">
          <QuestionContent question={question} />

          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <Badge variant={DIFFICULTY_VARIANT[question.difficulty]}>
              {DIFFICULTY_LABELS[question.difficulty]}
            </Badge>
            {askedOther && entry.requested_difficulty && (
              <Badge variant="outline" title="The difficulty this slot asked for">
                asked {DIFFICULTY_LABELS[entry.requested_difficulty].toLowerCase()}
              </Badge>
            )}
            <Badge variant="neutral">
              {entry.marks} mark{entry.marks === 1 ? "" : "s"}
            </Badge>
            {(question.printed_page !== null || question.chapter_number !== null) && (
              <span className="text-muted-foreground" title={question.chapter_title ?? undefined}>
                {[
                  question.printed_page !== null ? `p. ${question.printed_page}` : null,
                  question.chapter_number !== null ? `Ch ${question.chapter_number}` : null,
                ]
                  .filter(Boolean)
                  .join(", ")}
              </span>
            )}
            {optionDisagrees && (
              <Badge variant="warning" className="gap-1">
                <AlertTriangle className="size-3" /> Checker chose a different option
              </Badge>
            )}
          </div>

          {(question.answer || keyText) && (
            <details className="group rounded-md bg-muted/60 px-3 py-2 text-sm">
              <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
                Answer key
              </summary>
              <div className="mt-2 space-y-1 whitespace-pre-line">
                {keyText && (
                  <p className="font-medium">
                    <PaperText text={keyText} language={question.language} />
                  </p>
                )}
                {question.answer && (
                  <p>
                    <PaperText text={question.answer} language={question.language} />
                  </p>
                )}
              </div>
            </details>
          )}
        </div>

        {editable && (
          <div className="flex shrink-0 flex-col gap-1 sm:flex-row">
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Edit question ${number}`}
              title="Edit"
              disabled={replace.isPending}
              onClick={() => setEditing(true)}
            >
              <Pencil />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Replace question ${number}`}
              title="Replace with a new question"
              disabled={replace.isPending}
              onClick={() => setReplacing(true)}
            >
              <Shuffle />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove question ${number}`}
              title="Remove from paper"
              disabled={replace.isPending}
              onClick={() => setRemoving(true)}
            >
              <Trash2 />
            </Button>
          </div>
        )}
      </div>

      {replace.isPending && (
        <div className="absolute inset-0 flex items-center justify-center gap-2 rounded-lg bg-card/85 text-sm font-medium backdrop-blur-[1px]">
          <Loader2 className="size-4 animate-spin" /> Writing a new question… this can take about 10
          seconds.
        </div>
      )}

      <QuestionEditDialog
        open={editing}
        onOpenChange={setEditing}
        paperId={paper.id}
        entry={entry}
      />
      <ReplaceDialog
        open={replacing}
        onOpenChange={setReplacing}
        entry={entry}
        number={number}
        onReplace={(difficulty) => {
          setReplacing(false);
          replace.mutate({ entryId: entry.id, difficulty });
        }}
      />
      <ConfirmDialog
        open={removing}
        onOpenChange={setRemoving}
        title={`Remove question ${number}?`}
        description="It leaves this paper but stays in the question bank, so you can add it back later."
        confirmLabel="Remove question"
        loading={remove.isPending}
        onConfirm={() => remove.mutate(entry.id, { onSuccess: () => setRemoving(false) })}
      />
    </li>
  );
}

function ReplaceDialog({
  open,
  onOpenChange,
  entry,
  number,
  onReplace,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  entry: PaperQuestionRead;
  number: number;
  onReplace: (difficulty: QuestionDifficulty) => void;
}) {
  const initial = entry.requested_difficulty ?? entry.question.difficulty;
  const [difficulty, setDifficulty] = React.useState<QuestionDifficulty>(initial);

  React.useEffect(() => {
    if (open) setDifficulty(initial);
  }, [open, initial]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Replace question {number}?</DialogTitle>
          <DialogDescription>
            The agent writes a new {SECTION_LABELS[entry.question.type].toLowerCase()} question from
            the same chapters. The current one leaves the paper but stays in the question bank. This
            takes a few seconds.
          </DialogDescription>
        </DialogHeader>
        <ChoiceGroup
          label="Difficulty of the new question"
          value={difficulty}
          onChange={setDifficulty}
          options={(["easy", "medium", "hard"] as const).map((v) => ({
            value: v,
            label: DIFFICULTY_LABELS[v],
          }))}
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => onReplace(difficulty)}>
            <Shuffle /> Replace
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Note({
  icon: Icon,
  spin,
  tone = "default",
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  spin?: boolean;
  tone?: "default" | "destructive";
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm",
        tone === "destructive" ? "bg-destructive/10 text-destructive" : "bg-muted",
      )}
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", spin && "animate-spin")} />
      <p>{children}</p>
    </div>
  );
}
