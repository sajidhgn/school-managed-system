import { api } from "@/lib/api/client";
import type {
  BookCreate,
  BookDetail,
  BookPageRead,
  BookRead,
  BookSearchHit,
  BookUpdate,
  ChapterInput,
  ChapterRead,
  ChapterUpdate,
} from "@/lib/api/types";

/**
 * Mirrors backend/app/modules/books/router.py. Uploading QUEUES the chapter; the
 * agent (`app.cli process-books`, or the API itself with inline processing) reads,
 * orders, verifies and indexes it, and the chapter's `status` reports where it is.
 */
export const booksApi = {
  list: (classId?: string | null) =>
    api.get<BookRead[]>("/books", { params: { class_id: classId ?? undefined } }),
  get: (id: string) => api.get<BookDetail>(`/books/${id}`),
  create: (body: BookCreate) => api.post<BookDetail>("/books", body),
  update: (id: string, body: BookUpdate) => api.patch<BookDetail>(`/books/${id}`, body),
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
