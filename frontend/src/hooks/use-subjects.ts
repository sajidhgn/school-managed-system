"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { errorMessage } from "@/lib/api/errors";
import { subjectsMessages } from "@/lib/i18n/modules/subjects";
import { useCatalog } from "@/lib/i18n/use-catalog";
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
  const m = useCatalog(subjectsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SubjectCreate) => subjectsApi.create(body),
    onSuccess: (subject) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.subjects.all });
      toast.success(m.created, `${subject.code} — ${subject.name}`);
    },
    onError: (error) => toast.error(m.createFailed, errorMessage(error)),
  });
}

export function useUpdateSubject() {
  const m = useCatalog(subjectsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: SubjectUpdate }) =>
      subjectsApi.update(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.subjects.all });
      toast.success(m.updated);
    },
    onError: (error) => toast.error(m.updateFailed, errorMessage(error)),
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
  const m = useCatalog(subjectsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => subjectsApi.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.subjects.all });
      toast.success(m.deleted);
    },
    onError: (error) => toast.error(m.deleteFailed, errorMessage(error)),
  });
}

export function useAddToCurriculum() {
  const m = useCatalog(subjectsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ classId, body }: { classId: string; body: ClassSubjectCreate }) =>
      subjectsApi.curriculum.add(classId, body),
    onSuccess: (link) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.curriculum(link.class_id) });
      toast.success(m.addedToCurriculum, link.subject_name);
    },
    onError: (error) => toast.error(m.addFailed, errorMessage(error)),
  });
}

export function useUpdateCurriculumEntry() {
  const m = useCatalog(subjectsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ linkId, body }: { linkId: string; body: ClassSubjectUpdate }) =>
      subjectsApi.curriculum.update(linkId, body),
    onSuccess: (link) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.curriculum(link.class_id) });
      toast.success(m.curriculumUpdated);
    },
    onError: (error) => toast.error(m.curriculumUpdateFailed, errorMessage(error)),
  });
}

export function useRemoveFromCurriculum(classId: string) {
  const m = useCatalog(subjectsMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (linkId: string) => subjectsApi.curriculum.remove(linkId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.curriculum(classId) });
      toast.success(m.removedFromCurriculum);
    },
    onError: (error) => toast.error(m.removeFailed, errorMessage(error)),
  });
}
