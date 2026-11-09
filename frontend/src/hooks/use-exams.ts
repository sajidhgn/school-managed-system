"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { errorMessage } from "@/lib/api/errors";
import { fill } from "@/lib/i18n/format";
import { examsMessages } from "@/lib/i18n/modules/exams";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { queryKeys } from "@/lib/api/query-keys";
import { examsApi, type ExamListParams } from "@/lib/api/resources/exams";
import type {
  ExamCreate,
  ExamPaperCreate,
  ExamPaperUpdate,
  ExamUpdate,
  GradingScaleInput,
  MarksUpsert,
} from "@/lib/api/types";

export function useExams(params: ExamListParams = {}, { enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.exams.list(params),
    queryFn: () => examsApi.list(params),
    placeholderData: (previous) => previous,
    // Callers without `grade:read` (the students directory for a non-teaching
    // clerk) disable the fetch instead of collecting a 403.
    enabled,
  });
}

export function useExam(id: string | null) {
  return useQuery({
    queryKey: queryKeys.exams.detail(id ?? ""),
    queryFn: () => examsApi.get(id as string),
    enabled: Boolean(id),
  });
}

export function useExamPapers(examId: string | null) {
  return useQuery({
    queryKey: queryKeys.exams.papers(examId ?? ""),
    queryFn: () => examsApi.papers.list(examId as string),
    enabled: Boolean(examId),
  });
}

export function usePaperMarks(paperId: string | null) {
  return useQuery({
    queryKey: queryKeys.exams.marks(paperId ?? ""),
    queryFn: () => examsApi.marks.get(paperId as string),
    enabled: Boolean(paperId),
  });
}

export function useExamResults(examId: string, classId: string | null) {
  return useQuery({
    queryKey: queryKeys.exams.results(examId, classId ?? ""),
    queryFn: () => examsApi.results(examId, classId as string),
    enabled: Boolean(classId),
  });
}

export function useCreateExam() {
  const m = useCatalog(examsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ExamCreate) => examsApi.create(body),
    onSuccess: (exam) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.all });
      toast.success(m.created, exam.name);
    },
    onError: (error) => toast.error(m.createFailed, errorMessage(error)),
  });
}

export function useUpdateExam() {
  const m = useCatalog(examsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ExamUpdate }) => examsApi.update(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.all });
      toast.success(m.updated);
    },
    onError: (error) => toast.error(m.updateFailed, errorMessage(error)),
  });
}

/**
 * Delete an exam.
 *
 * The backend refuses (409) once any paper has marks — an exam with marks is a
 * term's academic record — and its message is surfaced verbatim.
 */
export function useDeleteExam() {
  const m = useCatalog(examsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => examsApi.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.all });
      toast.success(m.deleted);
    },
    onError: (error) => toast.error(m.deleteFailed, errorMessage(error)),
  });
}

export function useAddPaper(examId: string) {
  const m = useCatalog(examsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ExamPaperCreate) => examsApi.papers.add(examId, body),
    onSuccess: (paper) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.all });
      toast.success(m.paperAdded, `${paper.class_name} · ${paper.subject_name}`);
    },
    onError: (error) => toast.error(m.paperAddFailed, errorMessage(error)),
  });
}

export function useUpdatePaper(examId: string) {
  const m = useCatalog(examsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ paperId, body }: { paperId: string; body: ExamPaperUpdate }) =>
      examsApi.papers.update(paperId, body),
    onSuccess: (paper) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.papers(examId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.marks(paper.id) });
      toast.success(m.paperUpdated);
    },
    onError: (error) => toast.error(m.paperUpdateFailed, errorMessage(error)),
  });
}

export function useRemovePaper(examId: string) {
  const m = useCatalog(examsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (paperId: string) => examsApi.papers.remove(paperId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.papers(examId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.all });
      toast.success(m.paperRemoved);
    },
    onError: (error) => toast.error(m.paperRemoveFailed, errorMessage(error)),
  });
}

export function useSaveMarks(examId: string) {
  const m = useCatalog(examsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ paperId, body }: { paperId: string; body: MarksUpsert }) =>
      examsApi.marks.save(paperId, body),
    onSuccess: (result, { paperId }) => {
      // The sheet, the paper list (entered counts) and any cached result sheet
      // all read what was just written.
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.marks(paperId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.papers(examId) });
      void queryClient.invalidateQueries({ queryKey: ["exams", examId, "results"] });
      toast.success(
        m.marksSaved,
        result.saved === 1 ? m.entriesOne : fill(m.entriesMany, { count: result.saved }),
      );
    },
    onError: (error) => toast.error(m.marksSaveFailed, errorMessage(error)),
  });
}

/** The campus scale — the board scale until the campus saves its own. */
export function useGradingScale() {
  return useQuery({
    queryKey: queryKeys.exams.gradingScale,
    queryFn: () => examsApi.gradingScale.get(),
  });
}

/** Saving or resetting re-grades every result sheet, so all of `exams` refetches. */
export function useSetGradingScale() {
  const m = useCatalog(examsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: GradingScaleInput) => examsApi.gradingScale.set(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.all });
      toast.success(m.scaleSaved, m.scaleSavedDetail);
    },
    onError: (error) => toast.error(m.scaleSaveFailed, errorMessage(error)),
  });
}

export function useResetGradingScale() {
  const m = useCatalog(examsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => examsApi.gradingScale.reset(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.all });
      toast.success(m.scaleReset, m.scaleResetDetail);
    },
    onError: (error) => toast.error(m.scaleResetFailed, errorMessage(error)),
  });
}
