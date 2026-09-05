"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { examsApi, type ExamListParams } from "@/lib/api/resources/exams";
import type {
  ExamCreate,
  ExamPaperCreate,
  ExamPaperUpdate,
  ExamUpdate,
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
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ExamCreate) => examsApi.create(body),
    onSuccess: (exam) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.all });
      toast.success("Exam created", exam.name);
    },
    onError: (error) => toast.error("Couldn't create the exam", errorMessage(error)),
  });
}

export function useUpdateExam() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ExamUpdate }) => examsApi.update(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.all });
      toast.success("Exam updated");
    },
    onError: (error) => toast.error("Couldn't update the exam", errorMessage(error)),
  });
}

/**
 * Delete an exam.
 *
 * The backend refuses (409) once any paper has marks — an exam with marks is a
 * term's academic record — and its message is surfaced verbatim.
 */
export function useDeleteExam() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => examsApi.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.all });
      toast.success("Exam deleted");
    },
    onError: (error) => toast.error("Couldn't delete the exam", errorMessage(error)),
  });
}

export function useAddPaper(examId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ExamPaperCreate) => examsApi.papers.add(examId, body),
    onSuccess: (paper) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.all });
      toast.success("Paper added", `${paper.class_name} · ${paper.subject_name}`);
    },
    onError: (error) => toast.error("Couldn't add the paper", errorMessage(error)),
  });
}

export function useUpdatePaper(examId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ paperId, body }: { paperId: string; body: ExamPaperUpdate }) =>
      examsApi.papers.update(paperId, body),
    onSuccess: (paper) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.papers(examId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.marks(paper.id) });
      toast.success("Paper updated");
    },
    onError: (error) => toast.error("Couldn't update the paper", errorMessage(error)),
  });
}

export function useRemovePaper(examId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (paperId: string) => examsApi.papers.remove(paperId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.papers(examId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.exams.all });
      toast.success("Paper removed");
    },
    onError: (error) => toast.error("Couldn't remove the paper", errorMessage(error)),
  });
}

export function useSaveMarks(examId: string) {
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
      toast.success("Marks saved", `${result.saved} entr${result.saved === 1 ? "y" : "ies"}`);
    },
    onError: (error) => toast.error("Couldn't save the marks", errorMessage(error)),
  });
}
