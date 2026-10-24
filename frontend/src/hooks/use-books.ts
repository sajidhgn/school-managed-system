"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { booksApi } from "@/lib/api/resources/books";
import type {
  BookCreate,
  BookDetail,
  BookUpdate,
  ChapterInput,
  ChapterRead,
  ChapterStatus,
  ChapterUpdate,
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

export function useBooks(classId: string | null) {
  return useQuery({
    queryKey: queryKeys.books.list(classId),
    queryFn: () => booksApi.list(classId),
    placeholderData: (previous) => previous,
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
  const invalidate = useInvalidateBooks();
  return useMutation({
    mutationFn: (body: BookCreate) => booksApi.create(body),
    onSuccess: (book) => {
      invalidate();
      toast.success("Book added", `${book.title} — ${book.class_name}`);
    },
    onError: (error) =>
      toast.error("Couldn't add the book", errorMessage(error)),
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
  return useMutation({
    mutationFn: (files: File[]) => booksApi.scan(files),
    onError: (error) =>
      toast.error("Couldn't read the pages", errorMessage(error)),
  });
}

export function useUpdateBook(bookId: string) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidateBooks();
  return useMutation({
    mutationFn: (body: BookUpdate) => booksApi.update(bookId, body),
    onSuccess: (book) => {
      queryClient.setQueryData(queryKeys.books.detail(bookId), book);
      invalidate();
      toast.success("Book updated", book.title);
    },
    onError: (error) =>
      toast.error("Couldn't update the book", errorMessage(error)),
  });
}

export function useDeleteBook() {
  const invalidate = useInvalidateBooks();
  return useMutation({
    mutationFn: (id: string) => booksApi.remove(id),
    onSuccess: () => {
      invalidate();
      toast.success("Book deleted");
    },
    onError: (error) =>
      toast.error("Couldn't delete the book", errorMessage(error)),
  });
}

export function useAddChapter(bookId: string) {
  const invalidate = useInvalidateBooks();
  return useMutation({
    mutationFn: (body: ChapterInput) => booksApi.addChapter(bookId, body),
    onSuccess: (chapter) => {
      invalidate();
      toast.success(
        "Chapter added",
        `Chapter ${chapter.number}: ${chapter.title}`,
      );
    },
    onError: (error) =>
      toast.error("Couldn't add the chapter", errorMessage(error)),
  });
}

export function useUpdateChapter(bookId: string) {
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
    onError: (error) =>
      toast.error("Couldn't update the chapter", errorMessage(error)),
  });
}

export function useDeleteChapter(bookId: string) {
  const invalidate = useInvalidateBooks();
  return useMutation({
    mutationFn: (chapterId: string) =>
      booksApi.removeChapter(bookId, chapterId),
    onSuccess: () => {
      invalidate();
      toast.success("Chapter removed");
    },
    onError: (error) =>
      toast.error("Couldn't remove the chapter", errorMessage(error)),
  });
}

export function useUploadChapterFiles(bookId: string) {
  const onResult = useChapterResult(bookId);
  return useMutation({
    mutationFn: ({ chapterId, files }: { chapterId: string; files: File[] }) =>
      booksApi.uploadFiles(bookId, chapterId, files),
    onSuccess: (chapter, { files }) => {
      onResult(chapter);
      toast.success(
        `${files.length} file${files.length === 1 ? "" : "s"} uploaded`,
        chapter.status === "queued"
          ? "The agent will read and check the pages now."
          : undefined,
      );
    },
    onError: (error) => toast.error("Couldn't upload", errorMessage(error)),
  });
}

export function useDeleteChapterFile(bookId: string) {
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
    onError: (error) =>
      toast.error("Couldn't remove the file", errorMessage(error)),
  });
}

export function useProcessChapter(bookId: string) {
  const onResult = useChapterResult(bookId);
  return useMutation({
    mutationFn: (chapterId: string) => booksApi.process(bookId, chapterId),
    onSuccess: (chapter) => {
      onResult(chapter);
      toast.success(
        "Agent queued",
        `Chapter ${chapter.number} will be read and checked.`,
      );
    },
    onError: (error) =>
      toast.error("Couldn't start the agent", errorMessage(error)),
  });
}

export function useAcceptChapter(bookId: string) {
  const onResult = useChapterResult(bookId);
  return useMutation({
    mutationFn: (chapterId: string) => booksApi.accept(bookId, chapterId),
    onSuccess: (chapter) => {
      onResult(chapter);
      toast.success(
        "Chapter accepted",
        `Chapter ${chapter.number} is marked ready.`,
      );
    },
    onError: (error) =>
      toast.error("Couldn't accept the chapter", errorMessage(error)),
  });
}
