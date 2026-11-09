"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { queryKeys } from "@/lib/api/query-keys";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { fill } from "@/lib/i18n/format";
import { booksMessages } from "@/lib/i18n/modules/books";
import { useCatalog } from "@/lib/i18n/use-catalog";
import {
  booksApi,
  type BookListParams,
  type LibraryParams,
  type LibraryScopeParams,
} from "@/lib/api/resources/books";
import type {
  AskRequest,
  BookCreate,
  BookDetail,
  BookUpdate,
  ChapterInput,
  ChapterRead,
  ChapterStatus,
  ChapterUpdate,
  ShelfInput,
} from "@/lib/api/types";

/** Statuses the agent is still working through -- the page polls while any remain. */
export const BUSY_STATUSES: ReadonlySet<ChapterStatus> = new Set([
  "queued",
  "processing",
]);

/** A chapter waiting on an OpenAI batch (reading its pages, or embedding its
 * passages). Batches take hours, so the page checks back once a minute, not every
 * few seconds. */
function waitsOnBatch(chapter: {
  status: ChapterStatus;
  indexing?: boolean;
}): boolean {
  return chapter.status === "reading" || Boolean(chapter.indexing);
}

export function useBooks(params: BookListParams) {
  return useQuery({
    queryKey: queryKeys.books.list(params),
    queryFn: () => booksApi.list(params),
    placeholderData: (previous) => previous,
  });
}

/** The library every school shares, while `enabled` (the dialog is open). */
export function useLibrary(params: LibraryParams, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.books.library(params),
    queryFn: () => booksApi.library(params),
    enabled,
    placeholderData: (previous) => previous,
  });
}

export function useLibrarySubjects(grade: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.books.librarySubjects(grade),
    queryFn: () => booksApi.librarySubjects(grade),
    enabled,
    staleTime: 60_000,
  });
}

/** The book a refused "Add book" already is: in the library, or on the campus. */
export function duplicateBook(
  error: unknown,
): { bookId: string; onShelf: boolean } | null {
  if (!(error instanceof ApiError) || error.code !== "DUPLICATE_BOOK")
    return null;
  const bookId = error.problem.meta?.book_id;
  return typeof bookId === "string"
    ? { bookId, onShelf: error.problem.meta?.on_shelf === true }
    : null;
}

export function useAddFromLibrary() {
  const m = useCatalog(booksMessages).toast;
  const invalidate = useInvalidateBooks();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ShelfInput }) =>
      booksApi.addFromLibrary(id, body),
    onSuccess: (book) => {
      invalidate();
      toast.success(m.addedFromLibrary, `${book.title} — ${book.class_name}`);
    },
    onError: (error) => toast.error(m.addFailed, errorMessage(error)),
  });
}

export function useBook(id: string) {
  return useQuery({
    queryKey: queryKeys.books.detail(id),
    queryFn: () => booksApi.get(id),
    // Poll only while the agent has work in hand; a finished book is not refetched.
    refetchInterval: (query) => {
      const chapters = query.state.data?.chapters ?? [];
      if (chapters.some((c) => BUSY_STATUSES.has(c.status))) return 3000;
      return chapters.some(waitsOnBatch) ? 60_000 : false;
    },
  });
}

export function useChapterPages(
  bookId: string,
  chapterId: string,
  version: string | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: queryKeys.books.pages(bookId, chapterId, version),
    queryFn: () => booksApi.pages(bookId, chapterId),
    enabled,
  });
}

export function useBookSearch(bookId: string, q: string) {
  return useQuery({
    queryKey: queryKeys.books.search(bookId, q),
    queryFn: () => booksApi.search(bookId, q),
    enabled: q.trim().length >= 2,
    staleTime: 60_000,
  });
}

function useInvalidateBooks() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.books.all });
    void queryClient.invalidateQueries({ queryKey: ["books-search"] });
  };
}

/** Write a changed chapter straight into the cached book, then refresh around it. */
function useChapterResult(bookId: string) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidateBooks();
  return (chapter: ChapterRead) => {
    queryClient.setQueryData<BookDetail>(
      queryKeys.books.detail(bookId),
      (book) =>
        book
          ? {
              ...book,
              chapters: book.chapters.map((c) =>
                c.id === chapter.id ? chapter : c,
              ),
            }
          : book,
    );
    invalidate();
  };
}

export function useCreateBook() {
  const m = useCatalog(booksMessages).toast;
  const invalidate = useInvalidateBooks();
  return useMutation({
    mutationFn: (body: BookCreate) => booksApi.create(body),
    onSuccess: (book) => {
      invalidate();
      toast.success(m.added, `${book.title} — ${book.class_name}`);
    },
    // A book already in the library is answered in the dialog, with a way to add it.
    onError: (error) => {
      if (!duplicateBook(error)) toast.error(m.addFailed, errorMessage(error));
    },
  });
}

/** Whether "Read with AI" will work, checked when the dialog opens. */
export function useScanStatus(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.books.scanStatus,
    queryFn: () => booksApi.scanStatus(),
    enabled,
    staleTime: 60_000,
  });
}

/** Read a new book's details off its cover and contents pages. */
export function useScanBook() {
  const m = useCatalog(booksMessages).toast;
  return useMutation({
    mutationFn: (files: File[]) => booksApi.scan(files),
    onError: (error) => toast.error(m.scanFailed, errorMessage(error)),
  });
}

export function useUpdateBook(bookId: string) {
  const m = useCatalog(booksMessages).toast;
  const queryClient = useQueryClient();
  const invalidate = useInvalidateBooks();
  return useMutation({
    mutationFn: (body: BookUpdate) => booksApi.update(bookId, body),
    onSuccess: (book) => {
      queryClient.setQueryData(queryKeys.books.detail(bookId), book);
      invalidate();
      toast.success(m.updated, book.title);
    },
    onError: (error) => toast.error(m.updateFailed, errorMessage(error)),
  });
}

export function useDeleteBook() {
  const m = useCatalog(booksMessages).toast;
  const invalidate = useInvalidateBooks();
  return useMutation({
    mutationFn: (id: string) => booksApi.remove(id),
    onSuccess: () => {
      invalidate();
      toast.success(m.removed);
    },
    onError: (error) => toast.error(m.removeFailed, errorMessage(error)),
  });
}

export function useAddChapter(bookId: string) {
  const m = useCatalog(booksMessages).toast;
  const invalidate = useInvalidateBooks();
  return useMutation({
    mutationFn: (body: ChapterInput) => booksApi.addChapter(bookId, body),
    onSuccess: (chapter) => {
      invalidate();
      toast.success(
        m.chapterAdded,
        fill(m.chapterLabel, { number: chapter.number, title: chapter.title }),
      );
    },
    onError: (error) => toast.error(m.chapterAddFailed, errorMessage(error)),
  });
}

export function useUpdateChapter(bookId: string) {
  const m = useCatalog(booksMessages).toast;
  const onResult = useChapterResult(bookId);
  return useMutation({
    mutationFn: ({
      chapterId,
      body,
    }: {
      chapterId: string;
      body: ChapterUpdate;
    }) => booksApi.updateChapter(bookId, chapterId, body),
    onSuccess: onResult,
    onError: (error) => toast.error(m.chapterUpdateFailed, errorMessage(error)),
  });
}

export function useDeleteChapter(bookId: string) {
  const m = useCatalog(booksMessages).toast;
  const invalidate = useInvalidateBooks();
  return useMutation({
    mutationFn: (chapterId: string) =>
      booksApi.removeChapter(bookId, chapterId),
    onSuccess: () => {
      invalidate();
      toast.success(m.chapterRemoved);
    },
    onError: (error) => toast.error(m.chapterRemoveFailed, errorMessage(error)),
  });
}

export function useUploadChapterFiles(bookId: string) {
  const m = useCatalog(booksMessages).toast;
  const onResult = useChapterResult(bookId);
  return useMutation({
    mutationFn: ({ chapterId, files }: { chapterId: string; files: File[] }) =>
      booksApi.uploadFiles(bookId, chapterId, files),
    onSuccess: (chapter, { files }) => {
      onResult(chapter);
      toast.success(
        fill(files.length === 1 ? m.filesUploaded.one : m.filesUploaded.other, {
          count: files.length,
        }),
        chapter.status === "queued" ? m.agentWillRead : undefined,
      );
    },
    onError: (error) => toast.error(m.uploadFailed, errorMessage(error)),
  });
}

export function useDeleteChapterFile(bookId: string) {
  const m = useCatalog(booksMessages).toast;
  const onResult = useChapterResult(bookId);
  return useMutation({
    mutationFn: ({
      chapterId,
      fileId,
    }: {
      chapterId: string;
      fileId: string;
    }) => booksApi.removeFile(bookId, chapterId, fileId),
    onSuccess: onResult,
    onError: (error) => toast.error(m.fileRemoveFailed, errorMessage(error)),
  });
}

export function useProcessChapter(bookId: string) {
  const m = useCatalog(booksMessages).toast;
  const onResult = useChapterResult(bookId);
  return useMutation({
    mutationFn: (chapterId: string) => booksApi.process(bookId, chapterId),
    onSuccess: (chapter) => {
      onResult(chapter);
      toast.success(m.agentQueued, fill(m.agentQueuedBody, { number: chapter.number }));
    },
    onError: (error) => toast.error(m.agentFailed, errorMessage(error)),
  });
}

export function useAcceptChapter(bookId: string) {
  const m = useCatalog(booksMessages).toast;
  const onResult = useChapterResult(bookId);
  return useMutation({
    mutationFn: (chapterId: string) => booksApi.accept(bookId, chapterId),
    onSuccess: (chapter) => {
      onResult(chapter);
      toast.success(m.chapterAccepted, fill(m.chapterAcceptedBody, { number: chapter.number }));
    },
    onError: (error) => toast.error(m.acceptFailed, errorMessage(error)),
  });
}

/** Library-wide passage search. Runs once the query has two characters. */
export function useLibrarySearch(q: string, scope: LibraryScopeParams) {
  return useQuery({
    queryKey: queryKeys.books.librarySearch(q, { ...scope }),
    queryFn: () => booksApi.searchLibrary({ ...scope, q, limit: 12 }),
    enabled: q.length >= 2,
    placeholderData: (previous) => previous,
    // A missing AI key is a 503 that retrying will not fix.
    retry: false,
  });
}

/**
 * Ask the library. A mutation, not a query: each question is a paid model call the
 * user asked for, and must not re-run on focus or remount.
 */
export function useAskLibrary() {
  return useMutation({
    mutationFn: (body: AskRequest) => booksApi.ask(body),
  });
}
