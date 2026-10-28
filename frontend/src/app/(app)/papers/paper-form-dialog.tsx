"use client";

import * as React from "react";
import { AlertTriangle, Loader2, Plus, X } from "lucide-react";

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
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { useBooks } from "@/hooks/use-books";
import { useCreatePaper, usePaperSourceBook } from "@/hooks/use-papers";
import type {
  BookDetail,
  BookRead,
  ChapterRead,
  PaperDetail,
  PaperDifficulty,
  PaperLanguage,
  PaperType,
  QuestionType,
} from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { ChoiceGroup } from "./choice-group";
import {
  DEFAULT_MARKS,
  LANGUAGE_LABELS,
  MAX_CHAPTERS,
  MAX_QUESTIONS,
  MAX_SECTION_COUNT,
  MAX_MARKS,
  PAPER_DIFFICULTY_LABELS,
  PAPER_TYPE_HINTS,
  PAPER_TYPE_LABELS,
  QUESTION_TYPE_ORDER,
  SECTION_LABELS,
  SECTION_PRESETS,
  TYPES_FOR_PAPER,
  sectionProblems,
  type SectionRow,
} from "./paper-meta";

/** A chapter the agent has read -- the only kind a paper can be written from. */
function usable(chapter: ChapterRead): boolean {
  return (
    (chapter.status === "ready" || chapter.status === "needs_review") && chapter.page_count > 0
  );
}

const DIFFICULTY_HINTS: Record<PaperDifficulty, string> = {
  easy: "Every question easy.",
  medium: "Every question medium.",
  hard: "Every question hard.",
  mixed: "30% easy, 50% medium and 20% hard, in every section.",
};

/**
 * Ask the agent for a test paper: a book's chapters, the paper's language, level and
 * type, and how many questions of each kind at how many marks. Creating QUEUES the
 * paper -- the questions are written in the background, so the caller moves on to
 * the paper's page and watches it fill.
 */
export function PaperFormDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (paper: PaperDetail) => void;
}) {
  // A picker, not a browsing list: one page of the API's largest size. The list
  // page itself pages and searches in the database.
  const books = useBooks({ size: 100 });
  const bookList = books.data?.items;
  const create = useCreatePaper();

  const [bookId, setBookId] = React.useState("");
  const [chapterIds, setChapterIds] = React.useState<Set<string>>(new Set());
  const [title, setTitle] = React.useState("");
  // Until the teacher types a title, one is suggested from the book and chapters.
  const [titleTouched, setTitleTouched] = React.useState(false);
  const [language, setLanguage] = React.useState<PaperLanguage>("en");
  const [difficulty, setDifficulty] = React.useState<PaperDifficulty>("mixed");
  const [paperType, setPaperType] = React.useState<PaperType>("mix");
  const [rows, setRows] = React.useState<SectionRow[]>([]);
  const [duration, setDuration] = React.useState("");
  const [instructions, setInstructions] = React.useState("");
  const [attempted, setAttempted] = React.useState(false);
  const nextKey = React.useRef(1);

  const book = usePaperSourceBook(bookId || null);
  const detail = bookId && book.data?.id === bookId ? book.data : null;

  const presetRows = React.useCallback(
    (type: PaperType): SectionRow[] =>
      SECTION_PRESETS[type].map((s) => ({
        key: nextKey.current++,
        type: s.type,
        count: String(s.count),
        marks: String(s.marks ?? DEFAULT_MARKS[s.type]),
      })),
    [],
  );

  React.useEffect(() => {
    if (!open) return;
    setBookId("");
    setChapterIds(new Set());
    setTitle("");
    setTitleTouched(false);
    setLanguage("en");
    setDifficulty("mixed");
    setPaperType("mix");
    setRows(presetRows("mix"));
    setDuration("");
    setInstructions("");
    setAttempted(false);
  }, [open, presetRows]);

  const bookRow = bookList?.find((b) => b.id === bookId) ?? null;
  const chosenChapters = (detail?.chapters ?? [])
    .filter((c) => chapterIds.has(c.id))
    .sort((a, b) => a.number - b.number);

  // A string, so the effect below re-runs when the chosen numbers change and not on
  // every render's new array.
  const chapterNumbers = chosenChapters.map((c) => c.number).join(", ");
  React.useEffect(() => {
    if (titleTouched) return;
    setTitle(suggestTitle(bookRow, chapterNumbers));
  }, [titleTouched, bookRow, chapterNumbers]);

  const allowed = TYPES_FOR_PAPER[paperType];
  const usedTypes = new Set(rows.map((r) => r.type));
  const freeTypes = allowed.filter((t) => !usedTypes.has(t));
  const totalQuestions = rows.reduce((sum, r) => sum + (Number(r.count) || 0), 0);
  const totalMarks = rows.reduce(
    (sum, r) => sum + (Number(r.count) || 0) * (Number(r.marks) || DEFAULT_MARKS[r.type]),
    0,
  );

  const sectionIssues = sectionProblems(paperType, rows);
  const problems: string[] = [];
  if (!bookId) problems.push("Choose a book.");
  else if (!chapterIds.size) problems.push("Choose at least one chapter.");
  else if (chapterIds.size > MAX_CHAPTERS) {
    problems.push(`A paper can cover at most ${MAX_CHAPTERS} chapters.`);
  }
  if (!title.trim()) problems.push("Give the paper a title.");
  problems.push(...sectionIssues);
  if (duration.trim()) {
    const minutes = Number(duration);
    if (!Number.isInteger(minutes) || minutes < 5 || minutes > 600) {
      problems.push("Time allowed must be 5–600 minutes.");
    }
  }

  const updateRow = (key: number, patch: Partial<SectionRow>) =>
    setRows((current) => current.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  const addRow = () => {
    const type = freeTypes[0];
    if (!type) return;
    setRows((current) =>
      [
        ...current,
        {
          key: nextKey.current++,
          type,
          count: "5",
          marks: String(DEFAULT_MARKS[type]),
        },
      ].sort((a, b) => QUESTION_TYPE_ORDER.indexOf(a.type) - QUESTION_TYPE_ORDER.indexOf(b.type)),
    );
  };

  const toggleChapter = (id: string) =>
    setChapterIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>New test paper</DialogTitle>
          <DialogDescription>
            The agent writes the questions from the chapters you pick and checks each one against
            the book. It works in the background; you review and edit every question on the
            paper&apos;s page before printing.
          </DialogDescription>
        </DialogHeader>
        <form
          id="paper-form"
          className="space-y-5"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            setAttempted(true);
            if (problems.length) return;
            create.mutate(
              {
                title: title.trim(),
                book_id: bookId,
                chapter_ids: chosenChapters.map((c) => c.id),
                language,
                difficulty,
                paper_type: paperType,
                sections: rows.map((r) => ({
                  type: r.type,
                  count: Number(r.count),
                  marks: r.marks.trim() ? Number(r.marks) : null,
                })),
                duration_minutes: duration.trim() ? Number(duration) : null,
                instructions: instructions.trim() || null,
              },
              {
                onSuccess: (paper) => {
                  onOpenChange(false);
                  onCreated?.(paper);
                },
              },
            );
          }}
        >
          <div className="grid gap-1.5">
            <Label htmlFor="paper-book">Book</Label>
            <NativeSelect
              id="paper-book"
              value={bookId}
              onChange={(event) => {
                setBookId(event.target.value);
                setChapterIds(new Set());
              }}
            >
              <option value="" disabled>
                {books.isLoading ? "Loading books…" : "Choose a book"}
              </option>
              {groupByClass(bookList ?? []).map(([className, list]) => (
                <optgroup key={className} label={className}>
                  {list.map((b) => (
                    <option key={b.id} value={b.id}>
                      {`${b.title}${b.subject_name ? ` — ${b.subject_name}` : ""} (${b.ready_chapter_count}/${b.chapter_count} chapters ready)`}
                    </option>
                  ))}
                </optgroup>
              ))}
            </NativeSelect>
            {bookList && !bookList.length ? (
              <p className="text-xs text-muted-foreground">
                The library has no books yet. Add one under Books and let the agent read its
                chapters first.
              </p>
            ) : null}
          </div>

          {bookId && (
            <ChapterPicker
              book={detail}
              loading={book.isPending}
              selected={chapterIds}
              onToggle={toggleChapter}
              onSelect={setChapterIds}
            />
          )}

          <div className="grid gap-1.5">
            <Label htmlFor="paper-title">Title</Label>
            <Input
              id="paper-title"
              maxLength={200}
              value={title}
              placeholder="Science — Chapter 3 test"
              onChange={(event) => {
                setTitleTouched(true);
                setTitle(event.target.value);
              }}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <ChoiceGroup
              label="Language"
              value={language}
              onChange={setLanguage}
              options={(["en", "ur", "ar"] as const).map((v) => ({
                value: v,
                label: LANGUAGE_LABELS[v],
                lang: v,
              }))}
            />
            <ChoiceGroup
              label="Difficulty"
              value={difficulty}
              onChange={setDifficulty}
              hint={DIFFICULTY_HINTS[difficulty]}
              options={(["easy", "medium", "hard", "mixed"] as const).map((v) => ({
                value: v,
                label: PAPER_DIFFICULTY_LABELS[v],
              }))}
            />
          </div>

          <ChoiceGroup
            label="Paper type"
            value={paperType}
            onChange={(type) => {
              setPaperType(type);
              setRows(presetRows(type));
            }}
            hint={PAPER_TYPE_HINTS[paperType]}
            options={(["objective", "subjective", "mix"] as const).map((v) => ({
              value: v,
              label: PAPER_TYPE_LABELS[v],
            }))}
          />

          <fieldset className="space-y-2">
            <div className="flex items-center justify-between">
              <legend className="text-sm font-medium">Sections</legend>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={addRow}
                disabled={!freeTypes.length}
              >
                <Plus /> Add section
              </Button>
            </div>
            <div className="overflow-hidden rounded-lg border border-border">
              <div className="hidden grid-cols-[1fr_6rem_6rem_4rem_2.25rem] gap-2 border-b border-border bg-muted/50 px-3 py-1.5 text-xs text-muted-foreground sm:grid">
                <span>Question type</span>
                <span>Questions</span>
                <span>Marks each</span>
                <span className="text-end">Total</span>
                <span />
              </div>
              {rows.map((row) => {
                const options = allowed.filter((t) => t === row.type || !usedTypes.has(t));
                const each = Number(row.marks) || DEFAULT_MARKS[row.type];
                return (
                  <div
                    key={row.key}
                    className="grid grid-cols-[1fr_5rem_5rem_2.25rem] items-center gap-2 border-b border-border px-3 py-2 last:border-b-0 sm:grid-cols-[1fr_6rem_6rem_4rem_2.25rem]"
                  >
                    <NativeSelect
                      aria-label="Question type"
                      value={row.type}
                      className="col-span-4 sm:col-span-1"
                      onChange={(event) => {
                        const type = event.target.value as QuestionType;
                        // Carry the marks over only if the teacher changed them.
                        const keepMarks =
                          row.marks.trim() && Number(row.marks) !== DEFAULT_MARKS[row.type];
                        updateRow(row.key, {
                          type,
                          marks: keepMarks ? row.marks : String(DEFAULT_MARKS[type]),
                        });
                      }}
                    >
                      {options.map((t) => (
                        <option key={t} value={t}>
                          {SECTION_LABELS[t]}
                        </option>
                      ))}
                    </NativeSelect>
                    <Input
                      aria-label={`${SECTION_LABELS[row.type]}: number of questions`}
                      type="number"
                      min={1}
                      max={MAX_SECTION_COUNT}
                      value={row.count}
                      onChange={(event) => updateRow(row.key, { count: event.target.value })}
                    />
                    <Input
                      aria-label={`${SECTION_LABELS[row.type]}: marks per question`}
                      type="number"
                      min={1}
                      max={MAX_MARKS}
                      placeholder={String(DEFAULT_MARKS[row.type])}
                      value={row.marks}
                      onChange={(event) => updateRow(row.key, { marks: event.target.value })}
                    />
                    <span className="hidden text-end text-sm tabular-nums sm:block">
                      {(Number(row.count) || 0) * each}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove ${SECTION_LABELS[row.type]} section`}
                      onClick={() => setRows((current) => current.filter((r) => r.key !== row.key))}
                    >
                      <X />
                    </Button>
                  </div>
                );
              })}
              {!rows.length && (
                <p className="px-3 py-4 text-center text-sm text-muted-foreground">
                  No sections. Add one to say what the paper asks.
                </p>
              )}
            </div>
            <p
              className={cn(
                "text-sm",
                totalQuestions > MAX_QUESTIONS ? "text-destructive" : "text-muted-foreground",
              )}
            >
              <span className="font-medium text-foreground">{totalQuestions}</span> question
              {totalQuestions === 1 ? "" : "s"} ·{" "}
              <span className="font-medium text-foreground">{totalMarks}</span> mark
              {totalMarks === 1 ? "" : "s"} in all{" "}
              <span className="text-muted-foreground">(at most {MAX_QUESTIONS} questions)</span>
            </p>
            {sectionIssues.length > 0 && !attempted && (
              <ul className="space-y-0.5 text-sm text-destructive">
                {sectionIssues.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            )}
          </fieldset>

          <div className="grid gap-4 sm:grid-cols-[10rem_1fr]">
            <div className="grid content-start gap-1.5">
              <Label htmlFor="paper-duration">
                Time allowed <span className="font-normal text-muted-foreground">(minutes)</span>
              </Label>
              <Input
                id="paper-duration"
                type="number"
                min={5}
                max={600}
                value={duration}
                placeholder="Optional"
                onChange={(event) => setDuration(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="paper-instructions">
                Instructions <span className="font-normal text-muted-foreground">(optional)</span>
              </Label>
              <Textarea
                id="paper-instructions"
                dir="auto"
                maxLength={2000}
                rows={3}
                value={instructions}
                placeholder="Attempt all questions. Write neatly."
                onChange={(event) => setInstructions(event.target.value)}
              />
            </div>
          </div>

          {attempted && problems.length > 0 && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <ul className="space-y-0.5">
                {problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
          )}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={create.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="paper-form" loading={create.isPending}>
            Create paper
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ChapterPicker({
  book,
  loading,
  selected,
  onToggle,
  onSelect,
}: {
  book: BookDetail | null;
  loading: boolean;
  selected: Set<string>;
  onToggle: (id: string) => void;
  onSelect: (ids: Set<string>) => void;
}) {
  if (loading || !book) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Loading chapters…
      </p>
    );
  }
  const ready = book.chapters.filter(usable);
  const allChosen = ready.length > 0 && ready.every((c) => selected.has(c.id));

  return (
    <fieldset className="space-y-2">
      <div className="flex items-center justify-between">
        <legend className="text-sm font-medium">Chapters</legend>
        {ready.length > 1 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() =>
              onSelect(
                allChosen ? new Set() : new Set(ready.slice(0, MAX_CHAPTERS).map((c) => c.id)),
              )
            }
          >
            {allChosen ? "Clear" : "Select all ready"}
          </Button>
        )}
      </div>
      {!book.chapters.length ? (
        <p className="text-sm text-muted-foreground">This book has no chapters yet.</p>
      ) : (
        <ul className="max-h-52 divide-y divide-border overflow-y-auto rounded-lg border border-border">
          {book.chapters.map((chapter) => {
            const ok = usable(chapter);
            return (
              <li key={chapter.id}>
                <label
                  className={cn(
                    "flex items-center gap-2.5 px-3 py-2 text-sm",
                    ok ? "cursor-pointer hover:bg-accent/50" : "cursor-not-allowed opacity-60",
                  )}
                >
                  <input
                    type="checkbox"
                    disabled={!ok}
                    checked={selected.has(chapter.id)}
                    onChange={() => onToggle(chapter.id)}
                  />
                  <span className="min-w-0 flex-1 truncate">
                    Chapter {chapter.number}: {chapter.title}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {ok
                      ? `${chapter.page_count} page${chapter.page_count === 1 ? "" : "s"}`
                      : "Not read yet"}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      {book.chapters.length > 0 && !ready.length && (
        <p className="text-xs text-muted-foreground">
          None of this book&apos;s chapters has been read by the agent yet. Upload and process them
          on the book&apos;s page first.
        </p>
      )}
    </fieldset>
  );
}

function groupByClass(books: BookRead[]): [string, BookRead[]][] {
  const groups = new Map<string, BookRead[]>();
  for (const book of books) {
    const key = book.class_name ?? "Other";
    groups.set(key, [...(groups.get(key) ?? []), book]);
  }
  return [...groups.entries()];
}

/** "Science test — Chapters 3, 4", from the book and the chapters ticked so far. */
function suggestTitle(book: BookRead | null, chapterNumbers: string): string {
  if (!book) return "";
  const name = book.subject_name ?? book.title;
  if (!chapterNumbers) return `${name} test`;
  const label = chapterNumbers.includes(",")
    ? `Chapters ${chapterNumbers}`
    : `Chapter ${chapterNumbers}`;
  return `${name} test — ${label}`.slice(0, 200);
}
