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
  ChapterRead,
  ChapterStatus,
} from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { booksMessages } from "@/lib/i18n/modules/books";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { cn, formatDateTime } from "@/lib/utils";
import { BookFormDialog } from "../book-form-dialog";

const ACCEPTED_FILES = "application/pdf,image/jpeg,image/png,image/webp";

/** Badge colour per chapter status; the labels are in `booksMessages.status`. */
const STATUS_VARIANT: Record<ChapterStatus, BadgeProps["variant"]> = {
  empty: "neutral",
  uploaded: "neutral",
  queued: "default",
  reading: "default",
  processing: "default",
  ready: "success",
  needs_review: "warning",
  failed: "destructive",
};

type Refs = (typeof booksMessages)["en"]["refs"];
type Counted = { one: string; other: string };

/** `{ one, other }` picked by the count and filled with it. */
function counted(forms: Counted, count: number): string {
  return fill(count === 1 ? forms.one : forms.other, { count });
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function pageLabel(refs: Refs, printed: number | null, position: number): string {
  return printed !== null
    ? fill(refs.page, { n: printed })
    : fill(refs.pageNoNumber, { position });
}

/** Where a search hit sits: printed page numbers when known, else page positions. */
function hitPages(
  refs: Refs,
  hit: {
    printed_start: number | null;
    printed_end?: number | null;
    page_start: number;
    page_end: number;
  },
): string {
  if (hit.printed_start === null) {
    return fill(refs.pagePositions, { start: hit.page_start, end: hit.page_end });
  }
  return hit.printed_start === hit.printed_end
    ? fill(refs.page, { n: hit.printed_start })
    : fill(refs.pageRange, { start: hit.printed_start, end: hit.printed_end ?? "" });
}

export function BookDetailView({ bookId }: { bookId: string }) {
  const m = useCatalog(booksMessages).detail;
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
        <ArrowLeft className="size-4 rtl:rotate-180" /> {m.allBooks}
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
                <Pencil /> {data.can_edit ? m.edit : m.changeClass}
              </Button>
              <Button variant="outline" onClick={() => setDeleting(true)}>
                <Trash2 /> {deletes ? m.delete : m.remove}
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
            {data.school_count > 1
              ? fill(m.fromLibraryUsedBy, {
                  grade: data.grade,
                  count: data.school_count,
                })
              : fill(m.fromLibrary, { grade: data.grade })}
          </p>
        </div>
      )}

      <SearchCard book={data} />

      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">
            {m.chapters}{" "}
            <span className="font-normal text-muted-foreground">
              {fill(m.chaptersReady, {
                ready: data.ready_chapter_count,
                total: data.chapter_count,
              })}
            </span>
          </h2>
        </div>
        {data.chapters.map((chapter) => (
          <ChapterCard key={chapter.id} book={data} chapter={chapter} />
        ))}
        {data.can_edit && <AddChapterForm book={data} />}
        {!data.chapters.length && !data.can_edit && (
          <p className="text-sm text-muted-foreground">{m.noChapters}</p>
        )}
      </section>

      <BookFormDialog open={editing} onOpenChange={setEditing} book={data} />
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={fill(deletes ? m.deleteTitle : m.removeTitle, { title: data.title })}
        description={
          deletes
            ? m.deleteDescription
            : data.from_library
              ? m.removeLibraryDescription
              : counted(m.removeSharedDescription, others)
        }
        confirmLabel={deletes ? m.deleteBook : m.removeBook}
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
  const { detail: m, refs } = useCatalog(booksMessages);
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
          <Search className="size-4" /> {m.searchTitle}
        </CardTitle>
        <CardDescription>
          {m.searchDescription}{" "}
          {indexed ? (
            <Link
              href={`/books/ask?book=${book.id}`}
              className="font-medium text-primary hover:underline"
            >
              {m.askAboutBook}
            </Link>
          ) : null}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Input
          value={q}
          placeholder={indexed ? m.searchPlaceholder : m.processFirst}
          disabled={!indexed}
          maxLength={500}
          onChange={(event) => setQ(event.target.value)}
        />
        {debounced.length >= 2 &&
          (results.isFetching && !results.data ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> {m.searching}
            </p>
          ) : results.isError ? (
            <ErrorState error={results.error} className="py-6" />
          ) : !results.data?.length ? (
            <p className="text-sm text-muted-foreground">{m.noHits}</p>
          ) : (
            <ol className="space-y-2">
              {results.data.map((hit) => (
                <li
                  key={hit.chunk_id}
                  className="rounded-lg border border-border p-3"
                >
                  <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">
                      {fill(m.chapterHeading, {
                        number: hit.chapter_number,
                        title: hit.chapter_title,
                      })}
                    </span>
                    <span>{hitPages(refs, hit)}</span>
                    <Badge variant="outline">
                      {fill(refs.match, { percent: Math.round(hit.score * 100) })}
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
  const m = useCatalog(booksMessages).detail;
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
          {m.chapterNo}
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
          {m.title}
        </label>
        <Input
          id="new-chapter-title"
          required
          maxLength={200}
          value={title}
          placeholder={m.chapterTitlePlaceholder}
          onChange={(event) => setTitle(event.target.value)}
        />
      </div>
      <Button type="submit" variant="outline" loading={add.isPending}>
        <Plus /> {m.addChapter}
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
  const { detail: m, status: statusLabels } = useCatalog(booksMessages);
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
              aria-label={m.chapterNumberAria}
              type="number"
              min={1}
              max={999}
              className="w-20"
              value={number}
              onChange={(event) => setNumber(event.target.value)}
            />
            <Input
              aria-label={m.chapterTitleAria}
              className="min-w-48 flex-1"
              maxLength={200}
              required
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
            <Button type="submit" size="sm" loading={update.isPending}>
              {m.save}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setRenaming(false)}
            >
              {m.cancel}
            </Button>
          </form>
        ) : (
          <div className="space-y-1">
            <CardTitle>
              {fill(m.chapterHeading, { number: chapter.number, title: chapter.title })}
            </CardTitle>
            <CardDescription>
              {chapter.page_count
                ? counted(
                    chapter.indexing ? m.pagesIndexPending : m.pagesIndexed,
                    chapter.page_count,
                  )
                : counted(m.filesUploaded, chapter.files.length)}
              {chapter.processed_at
                ? ` · ${fill(m.checkedAt, { date: formatDateTime(chapter.processed_at) })}`
                : ""}
            </CardDescription>
          </div>
        )}
        <div className="flex items-center gap-1">
          <Badge variant={STATUS_VARIANT[chapter.status]} className="gap-1">
            {busy && <Loader2 className="size-3 animate-spin" />}
            {chapter.status === "reading" && <Clock className="size-3" />}
            {statusLabels[chapter.status]}
          </Badge>
          {editable && !renaming && (
            <>
              <Button
                variant="ghost"
                size="icon"
                aria-label={m.renameChapter}
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
                aria-label={m.removeChapter}
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
                    ? `${counted(m.filePages, file.page_count)} · `
                    : ""}
                  {formatSize(file.size_bytes)}
                </span>
                {editable && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    aria-label={fill(m.removeFile, { name: file.original_name })}
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
                ? m.uploading
                : chapter.files.length
                  ? m.addMorePages
                  : m.uploadChapter}
            </span>
            <span className="text-xs text-muted-foreground">{m.uploadHint}</span>
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
          <AgentNote icon={Bot}>{fill(m.noteQueued, { number: chapter.number })}</AgentNote>
        )}
        {chapter.status === "reading" && (
          <AgentNote icon={Clock}>{m.noteReading}</AgentNote>
        )}
        {chapter.status === "processing" && (
          <AgentNote icon={Loader2} spin>
            {m.noteProcessing}
          </AgentNote>
        )}
        {chapter.indexing && (
          <AgentNote icon={Clock}>{m.noteIndexing}</AgentNote>
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
                  <Bot /> {m.runAgent}
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  loading={runAgent.isPending}
                  onClick={() => runAgent.mutate(chapter.id)}
                >
                  <RotateCw /> {m.runAgain}
                </Button>
              ))}
            {canAccept && (
              <Button
                size="sm"
                variant="outline"
                loading={accept.isPending}
                onClick={() => accept.mutate(chapter.id)}
              >
                <CheckCircle2 /> {m.acceptAsIs}
              </Button>
            )}
            {hasPages && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowPages((v) => !v)}
              >
                {showPages
                  ? m.hidePages
                  : fill(m.showPages, { count: chapter.page_count })}
              </Button>
            )}
          </div>
        )}

        {showPages && hasPages && <PageList book={book} chapter={chapter} />}
      </CardContent>

      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={fill(m.removeChapterTitle, { number: chapter.number, title: chapter.title })}
        description={m.removeChapterDescription}
        confirmLabel={m.removeChapter}
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
  const m = useCatalog(booksMessages).detail;
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
        <Bot className="size-4" /> {m.agentCheck}
      </p>
      <p>
        {report.matches_declared && confidence >= 60 ? (
          <span className="text-success">
            {fill(m.verdictSure, { number: chapter.number, confidence })}
          </span>
        ) : report.matches_declared ? (
          <span className="text-warning-foreground dark:text-warning">
            {fill(m.verdictUnsure, { number: chapter.number, confidence })}
          </span>
        ) : report.detected_chapter_number !== null &&
          report.detected_chapter_number !== undefined ? (
          <span className="text-warning-foreground dark:text-warning">
            {detected
              ? fill(m.verdictOtherTitled, {
                  detected: report.detected_chapter_number,
                  title: detected.title,
                  confidence,
                  number: chapter.number,
                })
              : fill(m.verdictOther, {
                  detected: report.detected_chapter_number,
                  confidence,
                  number: chapter.number,
                })}
          </span>
        ) : (
          <span className="text-warning-foreground dark:text-warning">
            {m.verdictNone}
          </span>
        )}
      </p>
      <p className="text-muted-foreground">
        {[
          counted(m.reportPages, report.pages_total ?? 0),
          fill(m.reportTextLayer, { count: report.text_layer_pages ?? 0 }),
          fill(m.reportVision, { count: report.vision_pages ?? 0 }),
          counted(
            chapter.indexing ? m.reportPassagesWaiting : m.reportPassagesIndexed,
            report.chunks ?? 0,
          ),
        ].join(" · ")}
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
          {fill(m.acceptedBy, { name: report.accepted_by_name })}
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
  const { detail: m, refs, placement } = useCatalog(booksMessages);
  const pages = useChapterPages(
    book.id,
    chapter.id,
    chapter.processed_at,
    true,
  );

  if (pages.isLoading) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> {m.loadingPages}
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
                  alt={fill(m.pageAlt, { n: page.printed_page_number ?? page.position })}
                  loading="lazy"
                  className="h-48 w-full bg-muted object-cover object-top"
                />
              </a>
            )}
            <div className="space-y-1.5 p-3">
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="font-medium">
                  {pageLabel(refs, page.printed_page_number, page.position)}
                </span>
                <Badge variant="neutral">{placement[page.placement]}</Badge>
                <Badge variant="outline">
                  {page.method === "vision" ? m.readByAi : m.pdfText}
                </Badge>
                {page.opens_chapter && (
                  <Badge variant="default">{m.chapterStart}</Badge>
                )}
                {foreign && (
                  <Badge variant="warning">
                    {page.detected_chapter_number === null
                      ? m.notInChapterList
                      : fill(m.looksLikeChapter, { number: page.detected_chapter_number })}
                  </Badge>
                )}
              </div>
              <details>
                <summary className="cursor-pointer text-xs text-muted-foreground">
                  {page.text ? m.extractedText : m.noText}
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
