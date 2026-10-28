"use client";

import * as React from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Check, Library, Loader2, Plus, Search, Upload } from "lucide-react";

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
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { useAddFromLibrary, useLibrary, useLibrarySubjects } from "@/hooks/use-books";
import { useClassSummary } from "@/hooks/use-classes";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useCurriculum } from "@/hooks/use-subjects";
import type { LibraryBook } from "@/lib/api/types";

const PAGE_SIZE = 10;

/**
 * The library every school on the platform shares. A book another school already
 * uploaded is added to one of this campus's classes in one step -- its chapters,
 * pages and search index come with it, and nothing is uploaded or read again.
 *
 * Choosing one of the campus's classes narrows the library to that grade however
 * the uploader named it ("Class 5" also finds "Grade V"), and becomes the class the
 * book is added to.
 */
export function LibraryDialog({
  open,
  onOpenChange,
  onUploadInstead,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Closes the library and opens "Add a book" -- for a book nobody has uploaded. */
  onUploadInstead: () => void;
}) {
  const classes = useClassSummary();
  const [classId, setClassId] = React.useState("");
  const [subject, setSubject] = React.useState("");
  const [q, setQ] = React.useState("");
  const debounced = useDebouncedValue(q.trim(), 300);
  const [page, setPage] = React.useState(1);
  const [adding, setAdding] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setClassId("");
    setSubject("");
    setQ("");
    setPage(1);
    setAdding(null);
  }, [open]);

  const grade = classes.data?.find((c) => c.id === classId)?.name ?? "";

  // Any filter change starts again at page 1, adjusted during render so the stale
  // page is never fetched against the new filters.
  const filterKey = `${grade}|${subject}|${debounced}`;
  const [filteredBy, setFilteredBy] = React.useState(filterKey);
  if (filterKey !== filteredBy) {
    setFilteredBy(filterKey);
    setPage(1);
  }

  const subjects = useLibrarySubjects(grade, open);
  const library = useLibrary(
    {
      q: debounced || null,
      grade: grade || null,
      subject: subject || null,
      page,
      size: PAGE_SIZE,
    },
    open,
  );
  const filtered = Boolean(debounced || grade || subject);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Book library</DialogTitle>
          <DialogDescription>
            Books uploaded by schools on the platform. Add one to your class and use its chapters,
            pages and search at once: nothing is uploaded or read again.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-2 sm:grid-cols-[1fr_10rem_11rem]">
          <div className="relative">
            <Search
              className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              aria-label="Search the library by title or publisher"
              placeholder="Title or publisher…"
              value={q}
              maxLength={200}
              className="ps-9"
              onChange={(event) => setQ(event.target.value)}
            />
          </div>
          <NativeSelect
            aria-label="Class"
            value={classId}
            onChange={(event) => {
              setClassId(event.target.value);
              setSubject("");
            }}
          >
            <option value="">Any class</option>
            {classes.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect
            aria-label="Subject"
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
          >
            <option value="">Any subject</option>
            {subjects.data?.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </NativeSelect>
        </div>

        <div className="min-h-48">
          {library.isLoading ? (
            <p className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading the library…
            </p>
          ) : library.isError ? (
            <ErrorState
              error={library.error}
              onRetry={() => void library.refetch()}
              className="py-8"
            />
          ) : !library.data?.items.length ? (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <Library className="size-8 text-muted-foreground" aria-hidden />
              <div className="space-y-1">
                <p className="font-medium">
                  {filtered ? "Not in the library yet" : "The library is empty"}
                </p>
                <p className="text-sm text-muted-foreground">
                  Upload it once and every school using the same book can add it from here.
                </p>
              </div>
              <Button variant="outline" onClick={onUploadInstead}>
                <Upload /> Upload a new book
              </Button>
            </div>
          ) : (
            <>
              <ul className="space-y-2">
                {library.data.items.map((book) => (
                  <LibraryRow
                    key={book.id}
                    book={book}
                    open={adding === book.id}
                    onOpen={() => setAdding(book.id)}
                    onCancel={() => setAdding(null)}
                    classId={classId}
                    onAdded={() => onOpenChange(false)}
                  />
                ))}
              </ul>
              <Pagination
                meta={library.data.meta}
                onPageChange={setPage}
                disabled={library.isFetching}
              />
              <p className="pt-2 text-center text-sm text-muted-foreground">
                Not here?{" "}
                <button
                  type="button"
                  className="font-medium text-primary underline-offset-4 hover:underline"
                  onClick={onUploadInstead}
                >
                  Upload a new book
                </button>
              </p>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function LibraryRow({
  book,
  open,
  onOpen,
  onCancel,
  classId,
  onAdded,
}: {
  book: LibraryBook;
  open: boolean;
  onOpen: () => void;
  onCancel: () => void;
  /** The class the library is narrowed to: where the book goes unless changed. */
  classId: string;
  onAdded: () => void;
}) {
  const done = book.chapter_count > 0 && book.ready_chapter_count === book.chapter_count;
  const schools = book.school_count;

  return (
    <li className="space-y-3 rounded-lg border border-border p-3">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1 space-y-1">
          <p className="font-medium leading-snug">{book.title}</p>
          <p className="text-sm text-muted-foreground">
            {book.publisher} · {book.version}
          </p>
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <Badge variant="outline">{book.grade}</Badge>
            {book.subject ? <Badge variant="neutral">{book.subject}</Badge> : null}
            <Badge variant={done ? "success" : "neutral"}>
              {book.ready_chapter_count} / {book.chapter_count} chapters ready
            </Badge>
            {schools > 0 ? (
              <span className="text-muted-foreground">
                used by {schools} school{schools === 1 ? "" : "s"}
              </span>
            ) : null}
          </div>
        </div>
        {book.on_shelf ? (
          <Link
            href={`/books/${book.id}` as Route}
            className="shrink-0 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Badge variant="success" className="gap-1">
              <Check className="size-3" /> In your books
            </Badge>
          </Link>
        ) : !open ? (
          <Button size="sm" variant="outline" className="shrink-0" onClick={onOpen}>
            <Plus /> Add
          </Button>
        ) : null}
      </div>
      {open && !book.on_shelf ? (
        <AddToClassForm
          book={book}
          defaultClassId={classId}
          onCancel={onCancel}
          onAdded={onAdded}
        />
      ) : null}
    </li>
  );
}

/** Where the campus files the book: one of its classes, and a subject on it. */
function AddToClassForm({
  book,
  defaultClassId,
  onCancel,
  onAdded,
}: {
  book: LibraryBook;
  defaultClassId: string;
  onCancel: () => void;
  onAdded: () => void;
}) {
  const router = useRouter();
  const classes = useClassSummary();
  const add = useAddFromLibrary();
  const [classId, setClassId] = React.useState(defaultClassId);
  // null until picked: then the default is the class's subject named like the
  // uploader's, once the curriculum has loaded.
  const [chosenSubject, setSubjectId] = React.useState<string | null>(null);
  const curriculum = useCurriculum(classId || null);
  const sameName = curriculum.data?.find(
    (s) => s.subject_name.trim().toLowerCase() === book.subject?.trim().toLowerCase(),
  );
  const subjectId = chosenSubject ?? sameName?.subject_id ?? "";

  return (
    <form
      className="grid gap-2 rounded-md bg-muted/60 p-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
      onSubmit={(event) => {
        event.preventDefault();
        add.mutate(
          {
            id: book.id,
            body: { class_id: classId, subject_id: subjectId || null },
          },
          {
            onSuccess: (added) => {
              onAdded();
              router.push(`/books/${added.id}` as Route);
            },
          },
        );
      }}
    >
      <div className="grid gap-1.5">
        <Label htmlFor={`library-class-${book.id}`}>Add to class</Label>
        <NativeSelect
          id={`library-class-${book.id}`}
          required
          value={classId}
          onChange={(event) => {
            setClassId(event.target.value);
            setSubjectId(null);
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
        <Label htmlFor={`library-subject-${book.id}`}>
          Subject <span className="font-normal text-muted-foreground">(optional)</span>
        </Label>
        <NativeSelect
          id={`library-subject-${book.id}`}
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
      <div className="flex gap-2">
        <Button type="button" variant="ghost" onClick={onCancel} disabled={add.isPending}>
          Cancel
        </Button>
        <Button type="submit" loading={add.isPending} disabled={!classId}>
          Add book
        </Button>
      </div>
    </form>
  );
}
