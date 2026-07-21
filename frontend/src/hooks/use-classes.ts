"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { queryKeys } from "@/lib/api/query-keys";
import { errorMessage } from "@/lib/api/errors";
import { classesApi } from "@/lib/api/resources/classes";
import { ApiError } from "@/lib/api/errors";
import type {
  ClassCreate,
  ClassUpdate,
  PageParams,
  SectionCreate,
  SectionUpdate,
} from "@/lib/api/types";

export function useClasses(params: PageParams = {}) {
  return useQuery({
    queryKey: queryKeys.classes.list(params),
    queryFn: () => classesApi.list(params),
    placeholderData: (previous) => previous,
  });
}

/** Classes with section + headcount rollups. Powers the dashboard and pickers. */
export function useClassSummary() {
  return useQuery({
    queryKey: queryKeys.classes.summary,
    queryFn: () => classesApi.summary(),
  });
}

export function useCreateClass() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ClassCreate) => classesApi.create(body),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.all });
      toast.success("Class created", `${created.name} was added.`);
    },
    onError: (error) => toast.error("Couldn't create class", errorMessage(error)),
  });
}

export function useUpdateClass() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ClassUpdate }) => classesApi.update(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.all });
      toast.success("Class updated");
    },
    onError: (error) => toast.error("Couldn't update class", errorMessage(error)),
  });
}

/**
 * Delete a class.
 *
 * The backend refuses (409) while sections or students remain. That is a
 * meaningful safeguard, not a bug, so the message is surfaced verbatim rather
 * than replaced with a generic failure.
 */
export function useDeleteClass() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => classesApi.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.all });
      toast.success("Class deleted");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        toast.error("Class isn't empty", error.message);
        return;
      }
      toast.error("Couldn't delete class", errorMessage(error));
    },
  });
}

export function useSections(classId: string) {
  return useQuery({
    queryKey: queryKeys.classes.sections(classId),
    queryFn: () => classesApi.sections.list(classId),
    enabled: Boolean(classId),
  });
}

export function useCreateSection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ classId, body }: { classId: string; body: SectionCreate }) =>
      classesApi.sections.create(classId, body),
    onSuccess: (_section, { classId }) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.sections(classId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.summary });
      toast.success("Section added");
    },
    onError: (error) => toast.error("Couldn't add section", errorMessage(error)),
  });
}

export function useUpdateSection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      sectionId,
      body,
    }: {
      sectionId: string;
      classId: string;
      body: SectionUpdate;
    }) => classesApi.sections.update(sectionId, body),
    onSuccess: (_section, { classId }) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.sections(classId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.summary });
      toast.success("Section updated");
    },
    onError: (error) => toast.error("Couldn't update section", errorMessage(error)),
  });
}

export function useDeleteSection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ sectionId }: { sectionId: string; classId: string }) =>
      classesApi.sections.remove(sectionId),
    onSuccess: (_result, { classId }) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.sections(classId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.summary });
      toast.success("Section deleted");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        toast.error("Section isn't empty", error.message);
        return;
      }
      toast.error("Couldn't delete section", errorMessage(error));
    },
  });
}
