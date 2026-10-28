import { api } from "@/lib/api/client";
import type {
  BookCreate,
  BookDetail,
  BookPageRead,
  BookRead,
  BookScan,
  BookScanStatus,
  BookSearchHit,
  BookUpdate,
  ChapterInput,
  ChapterRead,
  ChapterUpdate,
  LibraryBook,
  Page,
  ShelfInput,
} from "@/lib/api/types";

/** The book list's filters and page, all applied by the API in the database. */
export interface BookListParams {
  class_id?: string | null;
  /** Title or publisher contains this. */
  q?: string | null;
  page?: number;
  size?: number;
}

/** The shared library's filters and page. */
export interface LibraryParams {
  /** Title or publisher contains this. */
  q?: string | null;
  /** A class name as any school writes it: "Class 5" also finds "Grade V". */
  grade?: string | null;
  /** One of `librarySubjects`. */
  subject?: string | null;
  page?: number;
  size?: number;
}

/**
 * Mirrors backend/app/modules/books/router.py. Uploading QUEUES the chapter; the
 * agent (`app.cli process-books`, or the API itself with inline processing) reads,
 * orders, verifies and indexes it, and the chapter's `status` reports where it is.
 */
export const booksApi = {
  list: (params: BookListParams = {}) =>
    api.get<Page<BookRead>>("/books", { params: { ...params } }),
  get: (id: string) => api.get<BookDetail>(`/books/${id}`),
  /** Every school's books -- uploaded once for the platform, added by any school. */
  library: (params: LibraryParams = {}) =>
    api.get<Page<LibraryBook>>("/books/library", { params: { ...params } }),
  librarySubjects: (grade?: string | null) =>
    api.get<string[]>("/books/library/subjects", { params: { grade: grade || undefined } }),
  /** File a library book under one of the campus's classes, instead of uploading it. */
  addFromLibrary: (id: string, body: ShelfInput) =>
    api.post<BookDetail>(`/books/library/${id}`, body),
  create: (body: BookCreate) => api.post<BookDetail>("/books", body),
  /** Photos or a PDF of a new book's cover and contents pages -> its details as
   * the AI read them. Nothing is saved; the answer pre-fills "Add a book". */
  scan: (files: File[]) => {
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    return api.upload<BookScan>("/books/scan", form);
  },
  /** Whether reading with AI will work: the provider's key, model and server. */
  scanStatus: () => api.get<BookScanStatus>("/books/scan/status"),
  update: (id: string, body: BookUpdate) => api.patch<BookDetail>(`/books/${id}`, body),
  /** Off the campus's books; deleted outright only when it uploaded it and no other
   * school uses it. */
  remove: (id: string) => api.delete<void>(`/books/${id}`),

  addChapter: (bookId: string, body: ChapterInput) =>
    api.post<ChapterRead>(`/books/${bookId}/chapters`, body),
  updateChapter: (bookId: string, chapterId: string, body: ChapterUpdate) =>
    api.patch<ChapterRead>(`/books/${bookId}/chapters/${chapterId}`, body),
  removeChapter: (bookId: string, chapterId: string) =>
    api.delete<void>(`/books/${bookId}/chapters/${chapterId}`),

  /** PDFs and/or page photos, in any order. `process` queues the agent at once. */
  uploadFiles: (bookId: string, chapterId: string, files: File[], process = true) => {
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    form.append("process", String(process));
    return api.upload<ChapterRead>(`/books/${bookId}/chapters/${chapterId}/files`, form);
  },
  removeFile: (bookId: string, chapterId: string, fileId: string) =>
    api.delete<ChapterRead>(`/books/${bookId}/chapters/${chapterId}/files/${fileId}`),
  process: (bookId: string, chapterId: string) =>
    api.post<ChapterRead>(`/books/${bookId}/chapters/${chapterId}/process`),
  accept: (bookId: string, chapterId: string) =>
    api.post<ChapterRead>(`/books/${bookId}/chapters/${chapterId}/accept`),

  pages: (bookId: string, chapterId: string) =>
    api.get<BookPageRead[]>(`/books/${bookId}/chapters/${chapterId}/pages`),
  search: (bookId: string, q: string, chapterId?: string) =>
    api.get<BookSearchHit[]>(`/books/${bookId}/search`, {
      params: { q, chapter_id: chapterId },
    }),
};

/** Same-origin URLs the BFF serves with the session attached -- usable in <img>/<a>. */
export const bookUrls = {
  pageImage: (bookId: string, pageId: string) => `/api/bff/books/${bookId}/pages/${pageId}/image`,
  file: (bookId: string, fileId: string) => `/api/bff/books/${bookId}/files/${fileId}`,
};
