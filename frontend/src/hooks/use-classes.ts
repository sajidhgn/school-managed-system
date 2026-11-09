"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { queryKeys } from "@/lib/api/query-keys";
import { errorMessage } from "@/lib/api/errors";
import { classesApi } from "@/lib/api/resources/classes";
import { ApiError } from "@/lib/api/errors";
import { fill } from "@/lib/i18n/format";
import { classesMessages } from "@/lib/i18n/modules/classes";
import { useCatalog } from "@/lib/i18n/use-catalog";
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
  const m = useCatalog(classesMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ClassCreate) => classesApi.create(body),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.all });
      toast.success(m.classCreated, fill(m.classCreatedBody, { name: created.name }));
    },
    onError: (error) => toast.error(m.classCreateFailed, errorMessage(error)),
  });
}

export function useUpdateClass() {
  const m = useCatalog(classesMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ClassUpdate }) => classesApi.update(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.all });
      toast.success(m.classUpdated);
    },
    onError: (error) => toast.error(m.classUpdateFailed, errorMessage(error)),
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
  const m = useCatalog(classesMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => classesApi.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.all });
      toast.success(m.classDeleted);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        toast.error(m.classNotEmpty, error.message);
        return;
      }
      toast.error(m.classDeleteFailed, errorMessage(error));
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
  const m = useCatalog(classesMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ classId, body }: { classId: string; body: SectionCreate }) =>
      classesApi.sections.create(classId, body),
    onSuccess: (_section, { classId }) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.sections(classId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.summary });
      toast.success(m.sectionAdded);
    },
    onError: (error) => toast.error(m.sectionAddFailed, errorMessage(error)),
  });
}

export function useUpdateSection() {
  const m = useCatalog(classesMessages).toast;
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
      toast.success(m.sectionUpdated);
    },
    onError: (error) => toast.error(m.sectionUpdateFailed, errorMessage(error)),
  });
}

export function useDeleteSection() {
  const m = useCatalog(classesMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ sectionId }: { sectionId: string; classId: string }) =>
      classesApi.sections.remove(sectionId),
    onSuccess: (_result, { classId }) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.sections(classId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.summary });
      toast.success(m.sectionDeleted);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        toast.error(m.sectionNotEmpty, error.message);
        return;
      }
      toast.error(m.sectionDeleteFailed, errorMessage(error));
    },
  });
}
