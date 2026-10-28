"use client";

import * as React from "react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { AlertTriangle, Library, PenLine, Plus, RotateCcw, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import {
  duplicateBook,
  useAddFromLibrary,
  useCreateBook,
  useScanBook,
  useScanStatus,
  useUpdateBook,
} from "@/hooks/use-books";
import { useClassSummary } from "@/hooks/use-classes";
import { useCurriculum } from "@/hooks/use-subjects";
import type { BookDetail, BookRead, BookScan } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { BookScanPanel } from "./book-scan-panel";

interface ChapterRow {
  key: number;
  number: string;
  title: string;
}

type Mode = "ai" | "manual";

const MODES: { value: Mode; label: string; icon: typeof Sparkles }[] = [
  { value: "ai", label: "Read with AI", icon: Sparkles },
  { value: "manual", label: "Manual", icon: PenLine },
];

/**
 * Add a book -- Title, Class, Publisher, Version -- with its chapter list, or edit a
 * book's details. The chapter list is what the agent checks every upload against,
 * so it is entered here first; chapters can still be added later on the book page.
 *
 * A new book can be typed in, or read by the AI off photos of its cover and
 * contents pages (`POST /books/scan`). The reading only fills in this form: the
 * teacher checks it and adds the book as usual. Whether the AI can read at all
 * (its provider's key, model and server) is checked when the dialog opens; if
 * not, the dialog starts on Manual and says why.
 *
 * Books are shared by every school, so one already in the library is refused
 * (`DUPLICATE_BOOK`); the dialog then offers to add that copy to the chosen class
 * instead. Editing a library book changes only where this campus files it -- the
 * title, publisher and version are its uploader's.
 */
export function BookFormDialog({
  open,
  onOpenChange,
  book,
  onCreated,
  onBrowseLibrary,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  book: BookRead | null;
  onCreated?: (book: BookDetail) => void;
  /** Shown on "Add a book": look in the shared library before uploading. */
  onBrowseLibrary?: () => void;
}) {
  const router = useRouter();
  const classes = useClassSummary();
  const create = useCreateBook();
  const addFromLibrary = useAddFromLibrary();
  const update = useUpdateBook(book?.id ?? "");
  const scan = useScanBook();
  const scanStatus = useScanStatus(open && !book);
  const aiProblem = scanStatus.data?.ready === false ? scanStatus.data.problem : null;

  // null until the teacher picks a tab: then the default follows whether the AI
  // is ready, even when that answer arrives after the dialog opened.
  const [chosenMode, setMode] = React.useState<Mode | null>(null);
  const mode: Mode = chosenMode ?? (aiProblem ? "manual" : "ai");
  const [scanFiles, setScanFiles] = React.useState<File[]>([]);
  const [scanned, setScanned] = React.useState<BookScan | null>(null);
  // Bumped whenever the dialog resets, so a reading that finishes after the
  // teacher closed or restarted it cannot overwrite the form.
  const scanRun = React.useRef(0);

  const [title, setTitle] = React.useState("");
  const [classId, setClassId] = React.useState("");
  const [publisher, setPublisher] = React.useState("");
  const [version, setVersion] = React.useState("");
  const [subjectId, setSubjectId] = React.useState("");
  const [rows, setRows] = React.useState<ChapterRow[]>([]);
  const nextKey = React.useRef(1);
  // The row just added by Enter / "Add chapter", so typing carries on in it.
  const focusKey = React.useRef<number | null>(null);

  const curriculum = useCurriculum(classId || null);
  // Only the uploader changes what the book IS; another campus refiles it.
  const detailsLocked = Boolean(book?.from_library);

  // A refusal names the book already in the library -- until the details change.
  const resetCreate = create.reset;
  React.useEffect(() => {
    resetCreate();
  }, [resetCreate, title, publisher, version, classId]);
  const duplicate = duplicateBook(create.error);

  React.useEffect(() => {
    if (!open) return;
    setTitle(book?.title ?? "");
    setClassId(book?.class_id ?? "");
    setPublisher(book?.publisher ?? "");
    setVersion(book?.version ?? "");
    setSubjectId(book?.subject_id ?? "");
    setRows(book ? [] : [{ key: nextKey.current++, number: "1", title: "" }]);
    setMode(null);
    setScanFiles([]);
    setScanned(null);
    scanRun.current++;
  }, [open, book]);

  const addRow = () =>
    setRows((current) => {
      const highest = Math.max(0, ...current.map((r) => Number(r.number) || 0));
      focusKey.current = nextKey.current;
      return [...current, { key: nextKey.current++, number: String(highest + 1), title: "" }];
    });

  React.useEffect(() => {
    if (focusKey.current === null) return;
    document.getElementById(`book-chapter-title-${focusKey.current}`)?.focus();
    focusKey.current = null;
  }, [rows]);

  const applyScan = (result: BookScan) => {
    setScanned(result);
    setTitle(result.title ?? "");
    setPublisher(result.publisher ?? "");
    setVersion(result.version ?? "");
    setClassId(result.class_id ?? "");
    setSubjectId(result.subject_id ?? "");
    setRows(
      result.chapters.length
        ? result.chapters.map((c) => ({
            key: nextKey.current++,
            number: String(c.number),
            title: c.title,
          }))
        : [{ key: nextKey.current++, number: "1", title: "" }],
    );
  };

  const readPages = () => {
    const run = ++scanRun.current;
    scan.mutate(scanFiles, {
      onSuccess: (result) => {
        if (run === scanRun.current) applyScan(result);
      },
    });
  };

  const chapters = rows
    .filter((r) => r.title.trim())
    .map((r) => ({ number: Number(r.number), title: r.title.trim() }));
  const numbers = chapters.map((c) => c.number);
  const duplicateNumber = numbers.length !== new Set(numbers).size;

  const pending = create.isPending || update.isPending || addFromLibrary.isPending;
  // "Read with AI" shows the upload step until a reading has filled in the form.
  const choosingPages = !book && mode === "ai" && !scanned;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{book ? "Edit book" : "Add a book"}</DialogTitle>
          <DialogDescription>
            {detailsLocked
              ? "This book is from the shared library. Choose the class and subject your school files it under; only the school that uploaded it can change its title, publisher or version."
              : book
                ? "Change the book's details. Its chapters and uploads are not affected."
                : choosingPages
                  ? "Upload the book's cover and contents pages. The AI fills in its details and chapter list for you to check."
                  : mode === "ai"
                    ? "Check what the AI read against the book and correct anything it got wrong. You upload each chapter's pages on the next screen."
                    : "Enter the book's details and its chapter list as printed in the contents page. You upload each chapter's pages on the next screen."}
          </DialogDescription>
        </DialogHeader>

        {!book && onBrowseLibrary && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Library className="size-4 shrink-0" aria-hidden />
            <span>
              Another school may have uploaded it already.{" "}
              <button
                type="button"
                className="font-medium text-primary underline-offset-4 hover:underline"
                onClick={onBrowseLibrary}
              >
                Search the library
              </button>
            </span>
          </p>
        )}

        {!book && (
          <div
            role="radiogroup"
            aria-label="How to add the book"
            className="inline-flex w-full rounded-[calc(var(--control-radius)+3px)] border border-input bg-card p-0.5 shadow-sm"
          >
            {MODES.map(({ value, label, icon: Icon }) => {
              const active = mode === value;
              return (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  disabled={scan.isPending}
                  onClick={() => setMode(value)}
                  className={cn(
                    "inline-flex h-8 min-w-0 flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-control px-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
                    active
                      ? "bg-primary font-medium text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                  )}
                >
                  {/* The icons go on the narrowest phones, where both labels only just fit. */}
                  <Icon className="hidden size-4 shrink-0 min-[400px]:block" />
                  <span className="truncate">{label}</span>
                </button>
              );
            })}
          </div>
        )}

        {choosingPages && aiProblem ? (
          <div className="flex items-start gap-2 rounded-lg bg-muted px-3 py-3 text-sm">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
            <div className="min-w-0 space-y-2">
              <p className="font-medium">Reading with AI isn&apos;t available right now.</p>
              <p className="text-muted-foreground">{aiProblem}</p>
              <Button type="button" variant="outline" size="sm" onClick={() => setMode("manual")}>
                <PenLine /> Enter it manually
              </Button>
            </div>
          </div>
        ) : choosingPages ? (
          <div className="space-y-2">
            <BookScanPanel
              files={scanFiles}
              onFilesChange={setScanFiles}
              reading={scan.isPending}
            />
            {scanStatus.data?.ready && (
              <p className="text-xs text-muted-foreground">
                Read by {scanStatus.data.model} on {scanStatus.data.provider}.
              </p>
            )}
          </div>
        ) : (
          <form
            id="book-form"
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (duplicateNumber) return;
              if (book) {
                update.mutate(
                  {
                    title,
                    class_id: classId,
                    publisher,
                    version,
                    subject_id: subjectId || null,
                    clear_subject: !subjectId,
                  },
                  { onSuccess: () => onOpenChange(false) },
                );
              } else {
                create.mutate(
                  {
                    title,
                    class_id: classId,
                    publisher,
                    version,
                    subject_id: subjectId || null,
                    chapters,
                  },
                  {
                    onSuccess: (created) => {
                      onOpenChange(false);
                      onCreated?.(created);
                    },
                  },
                );
              }
            }}
          >
            {!book && mode === "ai" && scanned && (
              <ScanSummary
                scan={scanned}
                classId={classId}
                subjectId={subjectId}
                onRestart={() => {
                  setScanned(null);
                  setScanFiles([]);
                }}
              />
            )}

            {duplicate && (
              <div className="flex flex-col gap-2 rounded-lg bg-primary/5 px-3 py-3 text-sm sm:flex-row sm:items-center">
                <Library className="hidden size-4 shrink-0 text-primary sm:block" />
                <p className="min-w-0 flex-1">{create.error?.message}</p>
                {duplicate.onShelf ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      onOpenChange(false);
                      router.push(`/books/${duplicate.bookId}` as Route);
                    }}
                  >
                    Open it
                  </Button>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    loading={addFromLibrary.isPending}
                    onClick={() =>
                      addFromLibrary.mutate(
                        {
                          id: duplicate.bookId,
                          body: {
                            class_id: classId,
                            subject_id: subjectId || null,
                          },
                        },
                        {
                          onSuccess: (added) => {
                            onOpenChange(false);
                            onCreated?.(added);
                          },
                        },
                      )
                    }
                  >
                    Add it to this class
                  </Button>
                )}
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-1.5 sm:col-span-2">
                <Label htmlFor="book-title">Title</Label>
                <Input
                  id="book-title"
                  required
                  disabled={detailsLocked}
                  maxLength={200}
                  value={title}
                  placeholder="New Countdown 5"
                  onChange={(event) => setTitle(event.target.value)}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="book-class">Class</Label>
                <NativeSelect
                  id="book-class"
                  required
                  value={classId}
                  onChange={(event) => {
                    setClassId(event.target.value);
                    setSubjectId("");
                  }}
                >
                  <option value="" disabled>
                    Choose a class
                  </option>
                  {classes.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </NativeSelect>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="book-subject">
                  Subject <span className="font-normal text-muted-foreground">(optional)</span>
                </Label>
                <NativeSelect
                  id="book-subject"
                  value={subjectId}
                  disabled={!classId}
                  onChange={(event) => setSubjectId(event.target.value)}
                >
                  <option value="">No subject</option>
                  {curriculum.data?.map((s) => (
                    <option key={s.subject_id} value={s.subject_id}>
                      {s.subject_name}
                    </option>
                  ))}
                </NativeSelect>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="book-publisher">Publisher</Label>
                <Input
                  id="book-publisher"
                  required
                  disabled={detailsLocked}
                  maxLength={200}
                  value={publisher}
                  placeholder="Oxford University Press"
                  onChange={(event) => setPublisher(event.target.value)}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="book-version">Version</Label>
                <Input
                  id="book-version"
                  required
                  disabled={detailsLocked}
                  maxLength={60}
                  value={version}
                  placeholder="3rd Edition, 2024"
                  onChange={(event) => setVersion(event.target.value)}
                />
              </div>
            </div>

            {!book && (
              <fieldset className="space-y-2">
                <div className="flex items-center justify-between">
                  <legend className="text-sm font-medium">Chapter list</legend>
                  <Button type="button" variant="ghost" size="sm" onClick={addRow}>
                    <Plus /> Add chapter
                  </Button>
                </div>
                <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                  {rows.map((row, index) => (
                    <div key={row.key} className="flex items-center gap-2">
                      <Input
                        aria-label={`Chapter ${index + 1} number`}
                        type="number"
                        min={1}
                        max={999}
                        className="w-20"
                        value={row.number}
                        onChange={(event) =>
                          setRows((current) =>
                            current.map((r) =>
                              r.key === row.key ? { ...r, number: event.target.value } : r,
                            ),
                          )
                        }
                      />
                      <Input
                        id={`book-chapter-title-${row.key}`}
                        aria-label={`Chapter ${index + 1} title`}
                        maxLength={200}
                        value={row.title}
                        placeholder="Chapter title"
                        onChange={(event) =>
                          setRows((current) =>
                            current.map((r) =>
                              r.key === row.key ? { ...r, title: event.target.value } : r,
                            ),
                          )
                        }
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault();
                            addRow();
                          }
                        }}
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label="Remove chapter"
                        onClick={() =>
                          setRows((current) => current.filter((r) => r.key !== row.key))
                        }
                      >
                        <X />
                      </Button>
                    </div>
                  ))}
                </div>
                {duplicateNumber ? (
                  <p className="text-sm text-destructive">Two chapters have the same number.</p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Rows without a title are skipped. Press Enter to add the next chapter.
                  </p>
                )}
              </fieldset>
            )}
          </form>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
            Cancel
          </Button>
          {choosingPages ? (
            <Button
              type="button"
              loading={scan.isPending}
              disabled={!scanFiles.length || Boolean(aiProblem)}
              onClick={readPages}
            >
              {!scan.isPending && <Sparkles />}
              {scan.isPending ? "Reading…" : "Read pages"}
            </Button>
          ) : (
            <Button type="submit" form="book-form" loading={pending} disabled={duplicateNumber}>
              {book ? "Save" : "Add book"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * What the AI filled in, and what it could not: a class or subject printed on the
 * pages that the campus (or this teacher) has no match for, or no chapter list.
 */
function ScanSummary({
  scan,
  classId,
  subjectId,
  onRestart,
}: {
  scan: BookScan;
  classId: string;
  subjectId: string;
  onRestart: () => void;
}) {
  const notes = [...(scan.notes ?? [])];
  if (!classId && scan.class_printed) {
    notes.push(
      `The pages say “${scan.class_printed}”, which isn't one of your classes — choose the class.`,
    );
  }
  if (classId && !subjectId && scan.subject_printed && !scan.subject_id) {
    notes.push(
      `The pages say “${scan.subject_printed}”, which isn't a subject you can file under for this class — choose one or leave it blank.`,
    );
  }
  if (!scan.chapters.length) {
    notes.push("No chapter list was found — add the chapters yourself.");
  }
  const pages = `${scan.pages_read} page${scan.pages_read === 1 ? "" : "s"}`;

  return (
    <div className="flex flex-col gap-1 rounded-lg bg-primary/5 px-3 py-2 text-sm sm:flex-row sm:items-start sm:gap-2">
      <div className="flex min-w-0 flex-1 items-start gap-2">
        <Sparkles className="mt-0.5 size-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1 space-y-1">
          <p>
            Filled in by AI from {pages}
            {scan.chapters.length
              ? `, with ${scan.chapters.length} chapter${scan.chapters.length === 1 ? "" : "s"}`
              : ""}
            . Check every field before adding the book.
          </p>
          {notes.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
              {notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="self-end sm:self-start"
        onClick={onRestart}
      >
        <RotateCcw /> Other pages
      </Button>
    </div>
  );
}
