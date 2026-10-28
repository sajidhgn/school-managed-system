import { api } from "@/lib/api/client";
import type {
  PaperCreate,
  PaperDetail,
  PaperLanguage,
  PaperQuestionAdd,
  PaperQuestionRead,
  PaperRead,
  PaperStatus,
  PaperUpdate,
  QuestionDifficulty,
  QuestionRead,
  QuestionType,
  QuestionUpdate,
  Page,
} from "@/lib/api/types";

/**
 * Mirrors backend/app/modules/papers/router.py. Creating (or regenerating) a paper
 * QUEUES it; the agent writes the questions from the chosen chapters, checks each
 * against the book, and the paper's `status` reports where it is. Every question it
 * writes is kept in the class's question bank, on the paper or not.
 */

export interface PaperListParams {
  class_id?: string | null;
  subject_id?: string | null;
  status?: PaperStatus | null;
  /** Title contains this. */
  q?: string | null;
  page?: number;
  size?: number;
}

export interface QuestionBankParams {
  class_id?: string | null;
  subject_id?: string | null;
  book_id?: string | null;
  chapter_id?: string | null;
  type?: QuestionType | null;
  difficulty?: QuestionDifficulty | null;
  language?: PaperLanguage | null;
  q?: string | null;
  page?: number;
  size?: number;
}

export const papersApi = {
  list: (params: PaperListParams = {}) =>
    api.get<Page<PaperRead>>("/papers", { params: { ...params } }),
  get: (id: string) => api.get<PaperDetail>(`/papers/${id}`),
  create: (body: PaperCreate) => api.post<PaperDetail>("/papers", body),
  update: (id: string, body: PaperUpdate) => api.patch<PaperDetail>(`/papers/${id}`, body),
  remove: (id: string) => api.delete<void>(`/papers/${id}`),
  /** Queues the paper again. Its questions leave the paper but stay in the bank. */
  regenerate: (id: string) => api.post<PaperDetail>(`/papers/${id}/regenerate`),

  bank: (params: QuestionBankParams = {}) =>
    api.get<Page<QuestionRead>>("/papers/questions", { params: { ...params } }),

  addQuestion: (paperId: string, body: PaperQuestionAdd) =>
    api.post<PaperQuestionRead>(`/papers/${paperId}/questions`, body),
  /** `entryId` is the question's place on the paper, not the bank question's id. */
  updateQuestion: (paperId: string, entryId: string, body: QuestionUpdate) =>
    api.patch<PaperQuestionRead>(`/papers/${paperId}/questions/${entryId}`, body),
  removeQuestion: (paperId: string, entryId: string) =>
    api.delete<void>(`/papers/${paperId}/questions/${entryId}`),
  /** Writes a new question for the slot there and then -- several seconds of AI. */
  replaceQuestion: (paperId: string, entryId: string, difficulty?: QuestionDifficulty | null) =>
    api.post<PaperQuestionRead>(`/papers/${paperId}/questions/${entryId}/replace`, {
      difficulty: difficulty ?? null,
    }),
};
