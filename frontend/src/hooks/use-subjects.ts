"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { subjectsApi, type SubjectListParams } from "@/lib/api/resources/subjects";
import type {
  ClassSubjectCreate,
  ClassSubjectUpdate,
  SubjectCreate,
  SubjectUpdate,
} from "@/lib/api/types";

export function useSubjects(params: SubjectListParams = {}) {
  return useQuery({
    queryKey: queryKeys.subjects.list(params),
    queryFn: () => subjectsApi.list(params),
    placeholderData: (previous) => previous,
  });
}

export function useCurriculum(classId: string | null) {
  return useQuery({
    queryKey: queryKeys.classes.curriculum(classId ?? ""),
    queryFn: () => subjectsApi.curriculum.list(classId as string),
    enabled: Boolean(classId),
  });
}

export function useCreateSubject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SubjectCreate) => subjectsApi.create(body),
    onSuccess: (subject) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.subjects.all });
      toast.success("Subject created", `${subject.code} — ${subject.name}`);
    },
    onError: (error) => toast.error("Couldn't create the subject", errorMessage(error)),
  });
}

export function useUpdateSubject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: SubjectUpdate }) =>
      subjectsApi.update(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.subjects.all });
      toast.success("Subject updated");
    },
    onError: (error) => toast.error("Couldn't update the subject", errorMessage(error)),
  });
}

/**
 * Delete a subject.
 *
 * The backend refuses (409) while any class still studies it, and names how many.
 * That is a safeguard against silently stripping a grade's curriculum — and, once
 * the gradebook lands, orphaning its marks — so the message is surfaced verbatim
 * rather than replaced with a generic failure.
 */
export function useDeleteSubject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => subjectsApi.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.subjects.all });
      toast.success("Subject deleted");
    },
    onError: (error) => toast.error("Couldn't delete the subject", errorMessage(error)),
  });
}

export function useAddToCurriculum() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ classId, body }: { classId: string; body: ClassSubjectCreate }) =>
      subjectsApi.curriculum.add(classId, body),
    onSuccess: (link) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.curriculum(link.class_id) });
      toast.success("Added to curriculum", link.subject_name);
    },
    onError: (error) => toast.error("Couldn't add the subject", errorMessage(error)),
  });
}

export function useUpdateCurriculumEntry() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ linkId, body }: { linkId: string; body: ClassSubjectUpdate }) =>
      subjectsApi.curriculum.update(linkId, body),
    onSuccess: (link) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.curriculum(link.class_id) });
      toast.success("Curriculum updated");
    },
    onError: (error) => toast.error("Couldn't update the curriculum", errorMessage(error)),
  });
}

export function useRemoveFromCurriculum(classId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (linkId: string) => subjectsApi.curriculum.remove(linkId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.curriculum(classId) });
      toast.success("Removed from curriculum");
    },
    onError: (error) => toast.error("Couldn't remove the subject", errorMessage(error)),
  });
}
