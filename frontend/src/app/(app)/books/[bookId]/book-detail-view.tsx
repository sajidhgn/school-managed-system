"use client";

import * as React from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  Clock,
  FileText,
  Image as ImageIcon,
  Library,
  Loader2,
  Pencil,
  Plus,
  RotateCw,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState, PageSpinner } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  BUSY_STATUSES,
  useAcceptChapter,
  useAddChapter,
  useBook,
  useBookSearch,
  useChapterPages,
  useDeleteBook,
  useDeleteChapter,
  useDeleteChapterFile,
  useProcessChapter,
  useUpdateChapter,
  useUploadChapterFiles,
} from "@/hooks/use-books";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { bookUrls } from "@/lib/api/resources/books";
import type {
  BookDetail,
  BookPageRead,
  ChapterRead,
  ChapterStatus,
} from "@/lib/api/types";
import { cn, formatDateTime } from "@/lib/utils";
import { BookFormDialog } from "../book-form-dialog";

const ACCEPTED_FILES = "application/pdf,image/jpeg,image/png,image/webp";

const STATUS: Record<
  ChapterStatus,
  { label: string; variant: BadgeProps["variant"] }
> = {
  empty: { label: "No pages yet", variant: "neutral" },
  uploaded: { label: "Not processed", variant: "neutral" },
  queued: { label: "Queued", variant: "default" },
  reading: { label: "OpenAI reading", variant: "default" },
  processing: { label: "Agent reading…", variant: "default" },
  ready: { label: "Ready", variant: "success" },
  needs_review: { label: "Needs review", variant: "warning" },
  failed: { label: "Failed", variant: "destructive" },
};

const PLACEMENT: Record<BookPageRead["placement"], string> = {
  printed_number: "by page number",
  pdf_order: "PDF order",
  agent: "placed by agent",
  upload_order: "upload order",
};

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function pageLabel(printed: number | null, position: number): string {
  return printed !== null ? `p. ${printed}` : `#${position} (no page number)`;
}

export function BookDetailView({ bookId }: { bookId: string }) {
  const router = useRouter();
  const book = useBook(bookId);
  const removeBook = useDeleteBook();
  const [editing, setEditing] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);

  if (book.isLoading) return <PageSpinner />;
  if (book.isError || !book.data) {
    return (
      <ErrorState error={book.error} onRetry={() => void book.refetch()} />
    );
  }
  const data = book.data;
  // Other campuses using it keep it: removing it here deletes it only when nobody does.
  const others = data.school_count - 1;
  const deletes = data.can_edit && others < 1;

  return (
    <div className="space-y-6">
      <Link
        href={"/books" as Route}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" /> All books
      </Link>
      <PageHeader
        title={data.title}
        description={[
          data.class_name,
          data.subject_name,
          data.publisher,
          data.version,
        ]
          .filter(Boolean)
          .join(" · ")}
        actions={
          data.can_remove ? (
            <>
              <Button variant="outline" onClick={() => setEditing(true)}>
                <Pencil /> {data.can_edit ? "Edit" : "Change class"}
              </Button>
              <Button variant="outline" onClick={() => setDeleting(true)}>
                <Trash2 /> {deletes ? "Delete" : "Remove"}
              </Button>
            </>
          ) : null
        }
      />

      {data.from_library && (
        <div className="flex items-start gap-2 rounded-lg bg-muted px-3 py-2 text-sm">
          <Library
            className="mt-0.5 size-4 shrink-0 text-muted-foreground"
            aria-hidden
          />
          <p>
            From the shared library: uploaded by another school, which keeps its
            chapters and pages up to date. Printed for {data.grade}
            {data.school_count > 1
              ? `, used by ${data.school_count} schools`
              : ""}
            .
          </p>
        </div>
      )}

      <SearchCard book={data} />

      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">
            Chapters{" "}
            <span className="font-normal text-muted-foreground">
              ({data.ready_chapter_count} of {data.chapter_count} ready)
            </span>
          </h2>
        </div>
        {data.chapters.map((chapter) => (
          <ChapterCard key={chapter.id} book={data} chapter={chapter} />
        ))}
        {data.can_edit && <AddChapterForm book={data} />}
        {!data.chapters.length && !data.can_edit && (
          <p className="text-sm text-muted-foreground">
            This book has no chapters yet.
          </p>
        )}
      </section>

      <BookFormDialog open={editing} onOpenChange={setEditing} book={data} />
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`${deletes ? "Delete" : "Remove"} ${data.title}?`}
        description={
          deletes
            ? "Every chapter, uploaded file, page and search index of this book is removed. This cannot be undone."
            : data.from_library
              ? "It leaves your school's books. The book stays in the shared library, and you can add it again later."
              : `${others} other school${others === 1 ? " uses" : "s use"} this book, so it stays in the library for them with its chapters and pages. It leaves your school's books; you can add it back from the library.`
        }
        confirmLabel={deletes ? "Delete book" : "Remove book"}
        loading={removeBook.isPending}
        onConfirm={() =>
          removeBook.mutate(data.id, {
            onSuccess: () => router.push("/books" as Route),
          })
        }
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

function SearchCard({ book }: { book: BookDetail }) {
  const [q, setQ] = React.useState("");
  const debounced = useDebouncedValue(q.trim(), 450);
  const results = useBookSearch(book.id, debounced);
  const indexed = book.chapters.some(
    (c) => c.status === "ready" || c.status === "needs_review",
  );

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2">
          <Search className="size-4" /> Search this book
        </CardTitle>
        <CardDescription>
          Finds passages by meaning, not just matching words — e.g. &ldquo;how
          to add fractions with different denominators&rdquo;.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Input
          value={q}
          placeholder={
            indexed
              ? "Ask about anything in the book…"
              : "Process a chapter first"
          }
          disabled={!indexed}
          maxLength={500}
          onChange={(event) => setQ(event.target.value)}
        />
        {debounced.length >= 2 &&
          (results.isFetching && !results.data ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Searching…
            </p>
          ) : results.isError ? (
            <ErrorState error={results.error} className="py-6" />
          ) : !results.data?.length ? (
            <p className="text-sm text-muted-foreground">
              Nothing in the indexed chapters matches.
            </p>
          ) : (
            <ol className="space-y-2">
              {results.data.map((hit) => (
                <li
                  key={hit.chunk_id}
                  className="rounded-lg border border-border p-3"
                >
                  <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">
                      Chapter {hit.chapter_number}: {hit.chapter_title}
                    </span>
                    <span>
                      {hit.printed_start !== null
                        ? hit.printed_start === hit.printed_end
                          ? `p. ${hit.printed_start}`
                          : `pp. ${hit.printed_start}–${hit.printed_end}`
                        : `pages #${hit.page_start}–${hit.page_end}`}
                    </span>
                    <Badge variant="outline">
                      {Math.round(hit.score * 100)}% match
                    </Badge>
                  </div>
                  <p className="line-clamp-4 whitespace-pre-line text-sm">
                    {hit.content}
                  </p>
                </li>
              ))}
            </ol>
          ))}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Chapters
// ---------------------------------------------------------------------------

function AddChapterForm({ book }: { book: BookDetail }) {
  const add = useAddChapter(book.id);
  const next = Math.max(0, ...book.chapters.map((c) => c.number)) + 1;
  const [number, setNumber] = React.useState(String(next));
  const [title, setTitle] = React.useState("");

  React.useEffect(() => setNumber(String(next)), [next]);

  return (
    <form
      className="flex flex-wrap items-end gap-2 rounded-xl border border-dashed border-border p-4"
      onSubmit={(event) => {
        event.preventDefault();
        add.mutate(
          { number: Number(number), title: title.trim() },
          { onSuccess: () => setTitle("") },
        );
      }}
    >
      <div className="grid gap-1.5">
        <label
          htmlFor="new-chapter-number"
          className="text-xs text-muted-foreground"
        >
          Chapter no.
        </label>
        <Input
          id="new-chapter-number"
          type="number"
          min={1}
          max={999}
          required
          className="w-24"
          value={number}
          onChange={(event) => setNumber(event.target.value)}
        />
      </div>
      <div className="grid min-w-56 flex-1 gap-1.5">
        <label
          htmlFor="new-chapter-title"
          className="text-xs text-muted-foreground"
        >
          Title
        </label>
        <Input
          id="new-chapter-title"
          required
          maxLength={200}
          value={title}
          placeholder="Chapter title"
          onChange={(event) => setTitle(event.target.value)}
        />
      </div>
      <Button type="submit" variant="outline" loading={add.isPending}>
        <Plus /> Add chapter
      </Button>
    </form>
  );
}

function ChapterCard({
  book,
  chapter,
}: {
  book: BookDetail;
  chapter: ChapterRead;
}) {
  const upload = useUploadChapterFiles(book.id);
  const removeFile = useDeleteChapterFile(book.id);
  const runAgent = useProcessChapter(book.id);
  const accept = useAcceptChapter(book.id);
  const update = useUpdateChapter(book.id);
  const remove = useDeleteChapter(book.id);

  const input = React.useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = React.useState(false);
  const [showPages, setShowPages] = React.useState(false);
  const [renaming, setRenaming] = React.useState(false);
  const [number, setNumber] = React.useState(String(chapter.number));
  const [title, setTitle] = React.useState(chapter.title);
  const [deleting, setDeleting] = React.useState(false);

  const busy = BUSY_STATUSES.has(chapter.status);
  // The API refuses file changes while a worker or a reading batch holds the files.
  const locked =
    chapter.status === "processing" || chapter.status === "reading";
  const editable = book.can_edit && !locked;
  const canRun = book.can_edit && chapter.files.length > 0 && !busy && !locked;
  const canAccept = book.can_edit && chapter.status === "needs_review";
  const hasPages = chapter.page_count > 0;
  const status = STATUS[chapter.status];
  const report = chapter.report;

  const send = (files: FileList | File[] | null) => {
    const list = Array.from(files ?? []);
    if (list.length) upload.mutate({ chapterId: chapter.id, files: list });
  };

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3 pb-3">
        {renaming ? (
          <form
            className="flex flex-1 flex-wrap items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              update.mutate(
                {
                  chapterId: chapter.id,
                  body: { number: Number(number), title: title.trim() },
                },
                { onSuccess: () => setRenaming(false) },
              );
            }}
          >
            <Input
              aria-label="Chapter number"
              type="number"
              min={1}
              max={999}
              className="w-20"
              value={number}
              onChange={(event) => setNumber(event.target.value)}
            />
            <Input
              aria-label="Chapter title"
              className="min-w-48 flex-1"
              maxLength={200}
              required
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
            <Button type="submit" size="sm" loading={update.isPending}>
              Save
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setRenaming(false)}
            >
              Cancel
            </Button>
          </form>
        ) : (
          <div className="space-y-1">
            <CardTitle>
              Chapter {chapter.number}: {chapter.title}
            </CardTitle>
            <CardDescription>
              {chapter.page_count
                ? `${chapter.page_count} page${chapter.page_count === 1 ? "" : "s"} ${
                    chapter.indexing ? "read · search index pending" : "indexed"
                  }`
                : `${chapter.files.length} file${chapter.files.length === 1 ? "" : "s"} uploaded`}
              {chapter.processed_at
                ? ` · checked ${formatDateTime(chapter.processed_at)}`
                : ""}
            </CardDescription>
          </div>
        )}
        <div className="flex items-center gap-1">
          <Badge variant={status.variant} className="gap-1">
            {busy && <Loader2 className="size-3 animate-spin" />}
            {chapter.status === "reading" && <Clock className="size-3" />}
            {status.label}
          </Badge>
          {editable && !renaming && (
            <>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Rename chapter"
                onClick={() => {
                  setNumber(String(chapter.number));
                  setTitle(chapter.title);
                  setRenaming(true);
                }}
              >
                <Pencil />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Remove chapter"
                onClick={() => setDeleting(true)}
              >
                <Trash2 />
              </Button>
            </>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {chapter.files.length > 0 && (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {chapter.files.map((file) => (
              <li
                key={file.id}
                className="flex items-center gap-3 px-3 py-2 text-sm"
              >
                {file.kind === "pdf" ? (
                  <FileText className="size-4 shrink-0 text-muted-foreground" />
                ) : (
                  <ImageIcon className="size-4 shrink-0 text-muted-foreground" />
                )}
                <a
                  href={bookUrls.file(book.id, file.id)}
                  target="_blank"
                  rel="noreferrer"
                  className="min-w-0 flex-1 truncate hover:underline"
                >
                  {file.original_name}
                </a>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {file.kind === "pdf"
                    ? `${file.page_count} page${file.page_count === 1 ? "" : "s"} · `
                    : ""}
                  {formatSize(file.size_bytes)}
                </span>
                {editable && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    aria-label={`Remove ${file.original_name}`}
                    disabled={removeFile.isPending}
                    onClick={() =>
                      removeFile.mutate({
                        chapterId: chapter.id,
                        fileId: file.id,
                      })
                    }
                  >
                    <X />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}

        {editable && (
          <div
            role="button"
            tabIndex={0}
            onClick={() => input.current?.click()}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                input.current?.click();
              }
            }}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              send(event.dataTransfer.files);
            }}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm transition-colors hover:bg-accent/50",
              dragging && "border-primary bg-primary/5",
            )}
          >
            {upload.isPending ? (
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            ) : (
              <Upload className="size-5 text-muted-foreground" />
            )}
            <span className="font-medium">
              {upload.isPending
                ? "Uploading…"
                : chapter.files.length
                  ? "Add more pages"
                  : "Upload this chapter"}
            </span>
            <span className="text-xs text-muted-foreground">
              A PDF, or photos of the pages in any order — JPEG, PNG or WebP.
              Drop files here or click to choose.
            </span>
            <input
              ref={input}
              type="file"
              multiple
              accept={ACCEPTED_FILES}
              className="hidden"
              onChange={(event) => {
                send(event.target.files);
                event.target.value = "";
              }}
            />
          </div>
        )}

        {chapter.status === "queued" && (
          <AgentNote icon={Bot}>
            Waiting for the agent. It reads every page, sorts them by page
            number, checks they belong to Chapter {chapter.number}, and indexes
            the text.
          </AgentNote>
        )}
        {chapter.status === "reading" && (
          <AgentNote icon={Clock}>
            OpenAI is reading the scanned pages in a batch, at half the usual
            price. This usually takes a few hours and at most 24; the agent then
            finishes the chapter by itself. Its files can&apos;t be changed
            until then.
          </AgentNote>
        )}
        {chapter.status === "processing" && (
          <AgentNote icon={Loader2} spin>
            The agent is reading the pages and checking them against the chapter
            list…
          </AgentNote>
        )}
        {chapter.indexing && (
          <AgentNote icon={Clock}>
            The pages are ready to read. Search will include this chapter once
            OpenAI finishes indexing it in a batch — usually within a few hours,
            at most 24.
          </AgentNote>
        )}
        {chapter.status === "failed" && chapter.error && (
          <AgentNote icon={AlertTriangle} tone="destructive">
            {chapter.error}
          </AgentNote>
        )}

        {report && <AgentReport chapter={chapter} book={book} />}

        {/* Rendered only with something in it: an empty row would still take a
            space-y gap at the bottom of the card. */}
        {(canRun || canAccept || hasPages) && (
          <div className="flex flex-wrap gap-2">
            {canRun &&
              (chapter.status === "uploaded" ? (
                <Button
                  size="sm"
                  loading={runAgent.isPending}
                  onClick={() => runAgent.mutate(chapter.id)}
                >
                  <Bot /> Run agent
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  loading={runAgent.isPending}
                  onClick={() => runAgent.mutate(chapter.id)}
                >
                  <RotateCw /> Run agent again
                </Button>
              ))}
            {canAccept && (
              <Button
                size="sm"
                variant="outline"
                loading={accept.isPending}
                onClick={() => accept.mutate(chapter.id)}
              >
                <CheckCircle2 /> Accept as it is
              </Button>
            )}
            {hasPages && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowPages((v) => !v)}
              >
                {showPages
                  ? "Hide pages"
                  : `Show pages (${chapter.page_count})`}
              </Button>
            )}
          </div>
        )}

        {showPages && hasPages && <PageList book={book} chapter={chapter} />}
      </CardContent>

      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Remove Chapter ${chapter.number}: ${chapter.title}?`}
        description="Its uploaded files, pages and search index are deleted with it."
        confirmLabel="Remove chapter"
        loading={remove.isPending}
        onConfirm={() =>
          remove.mutate(chapter.id, { onSuccess: () => setDeleting(false) })
        }
      />
    </Card>
  );
}

function AgentNote({
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
        "flex items-start gap-2 rounded-lg px-3 py-2 text-sm",
        tone === "destructive"
          ? "bg-destructive/10 text-destructive"
          : "bg-muted",
      )}
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", spin && "animate-spin")} />
      <p>{children}</p>
    </div>
  );
}

function AgentReport({
  book,
  chapter,
}: {
  book: BookDetail;
  chapter: ChapterRead;
}) {
  const report = chapter.report;
  if (!report) return null;
  const detected = book.chapters.find(
    (c) => c.number === report.detected_chapter_number,
  );
  const confidence = Math.round((report.detected_confidence ?? 0) * 100);
  // The headline already states the chapter verdict; the list carries the rest.
  const issues = (report.issues ?? []).filter(
    (issue) =>
      issue.code !== "chapter_mismatch" && issue.code !== "low_confidence",
  );

  return (
    <div className="space-y-2 rounded-lg border border-border p-3 text-sm">
      <p className="flex items-center gap-2 font-medium">
        <Bot className="size-4" /> Agent check
      </p>
      <p>
        {report.matches_declared && confidence >= 60 ? (
          <span className="text-success">
            This is Chapter {chapter.number} ({confidence}% sure).
          </span>
        ) : report.matches_declared ? (
          <span className="text-warning-foreground dark:text-warning">
            Probably Chapter {chapter.number}, but only {confidence}% sure —
            check the pages.
          </span>
        ) : report.detected_chapter_number !== null &&
          report.detected_chapter_number !== undefined ? (
          <span className="text-warning-foreground dark:text-warning">
            This looks like Chapter {report.detected_chapter_number}
            {detected ? `: ${detected.title}` : ""} ({confidence}%), not Chapter{" "}
            {chapter.number}.
          </span>
        ) : (
          <span className="text-warning-foreground dark:text-warning">
            This upload does not match any chapter in the list.
          </span>
        )}
      </p>
      <p className="text-muted-foreground">
        {report.pages_total} page{report.pages_total === 1 ? "" : "s"} ·{" "}
        {report.text_layer_pages} from the PDF&apos;s text ·{" "}
        {report.vision_pages} read from the image · {report.chunks} passage
        {report.chunks === 1 ? "" : "s"}{" "}
        {chapter.indexing ? "waiting to be indexed" : "indexed"}
      </p>
      {issues.length > 0 && (
        <ul className="space-y-1">
          {issues.map((issue, index) => (
            <li
              key={`${issue.code}-${index}`}
              className="flex items-start gap-2"
            >
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" />
              <span>{issue.message}</span>
            </li>
          ))}
        </ul>
      )}
      {report.accepted_by_name && (
        <p className="text-xs text-muted-foreground">
          Accepted by {report.accepted_by_name}.
        </p>
      )}
    </div>
  );
}

function PageList({
  book,
  chapter,
}: {
  book: BookDetail;
  chapter: ChapterRead;
}) {
  const pages = useChapterPages(
    book.id,
    chapter.id,
    chapter.processed_at,
    true,
  );

  if (pages.isLoading) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Loading pages…
      </p>
    );
  }
  if (pages.isError) return <ErrorState error={pages.error} className="py-6" />;

  return (
    <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {pages.data?.map((page) => {
        const foreign =
          page.detected_chapter_number !== chapter.number &&
          (page.chapter_confidence ?? 0) >= 0.6;
        return (
          <li
            key={page.id}
            className={cn(
              "overflow-hidden rounded-lg border",
              foreign ? "border-warning" : "border-border",
            )}
          >
            {page.has_image && (
              <a
                href={bookUrls.pageImage(book.id, page.id)}
                target="_blank"
                rel="noreferrer"
              >
                {/* eslint-disable-next-line @next/next/no-img-element -- served by the BFF with the session attached */}
                <img
                  src={bookUrls.pageImage(book.id, page.id)}
                  alt={`Page ${page.printed_page_number ?? page.position}`}
                  loading="lazy"
                  className="h-48 w-full bg-muted object-cover object-top"
                />
              </a>
            )}
            <div className="space-y-1.5 p-3">
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="font-medium">
                  {pageLabel(page.printed_page_number, page.position)}
                </span>
                <Badge variant="neutral">{PLACEMENT[page.placement]}</Badge>
                <Badge variant="outline">
                  {page.method === "vision" ? "read by AI" : "PDF text"}
                </Badge>
                {page.opens_chapter && (
                  <Badge variant="default">chapter start</Badge>
                )}
                {foreign && (
                  <Badge variant="warning">
                    {page.detected_chapter_number === null
                      ? "not in chapter list"
                      : `looks like Ch ${page.detected_chapter_number}`}
                  </Badge>
                )}
              </div>
              <details>
                <summary className="cursor-pointer text-xs text-muted-foreground">
                  {page.text ? "Extracted text" : "No text could be read"}
                </summary>
                {page.text && (
                  <p className="mt-2 max-h-64 overflow-y-auto whitespace-pre-line text-xs">
                    {page.text}
                  </p>
                )}
              </details>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
