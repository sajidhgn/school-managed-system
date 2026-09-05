import { api } from "@/lib/api/client";
import type {
  ExamClassResults,
  ExamCreate,
  ExamPaperCreate,
  ExamPaperRead,
  ExamPaperUpdate,
  ExamRead,
  ExamUpdate,
  MarksUpsert,
  MarksUpsertResult,
  Page,
  PageParams,
  PaperMarksRead,
} from "@/lib/api/types";

/** Mirrors backend/app/modules/exams/router.py. */

export interface ExamListParams extends PageParams {
  q?: string | null;
}

export const examsApi = {
  list: (params: ExamListParams = {}) =>
    api.get<Page<ExamRead>>("/exams", { params: { ...params } }),

  get: (id: string) => api.get<ExamRead>(`/exams/${id}`),

  create: (body: ExamCreate) => api.post<ExamRead>("/exams", body),

  update: (id: string, body: ExamUpdate) => api.patch<ExamRead>(`/exams/${id}`, body),

  /** 409s once any paper has marks — an exam with marks is the academic record. */
  remove: (id: string) => api.delete<void>(`/exams/${id}`),

  papers: {
    list: (examId: string) => api.get<ExamPaperRead[]>(`/exams/${examId}/papers`),

    add: (examId: string, body: ExamPaperCreate) =>
      api.post<ExamPaperRead>(`/exams/${examId}/papers`, body),

    update: (paperId: string, body: ExamPaperUpdate) =>
      api.patch<ExamPaperRead>(`/exams/papers/${paperId}`, body),

    /** 409s once marked, same reasoning as exam delete. */
    remove: (paperId: string) => api.delete<void>(`/exams/papers/${paperId}`),
  },

  marks: {
    /** The full mark sheet: every student of the paper's class, marks merged in. */
    get: (paperId: string) => api.get<PaperMarksRead>(`/exams/papers/${paperId}/marks`),

    /** Upsert — resubmitting after a correction overwrites; omitted students are untouched. */
    save: (paperId: string, body: MarksUpsert) =>
      api.put<MarksUpsertResult>(`/exams/papers/${paperId}/marks`, body),
  },

  /** Result sheet for one class: papers as columns, students ranked. */
  results: (examId: string, classId: string) =>
    api.get<ExamClassResults>(`/exams/${examId}/results`, { params: { class_id: classId } }),
};
