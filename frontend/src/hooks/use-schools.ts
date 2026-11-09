"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { queryKeys } from "@/lib/api/query-keys";
import { errorMessage } from "@/lib/api/errors";
import { fill } from "@/lib/i18n/format";
import { adminMessages } from "@/lib/i18n/modules/admin";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { schoolsApi, type SchoolListParams } from "@/lib/api/resources/schools";
import type { SchoolCreate, SchoolUpdate } from "@/lib/api/types";

export function useSchools(params: SchoolListParams = {}) {
  return useQuery({
    queryKey: queryKeys.schools.list(params),
    queryFn: () => schoolsApi.list(params),
    placeholderData: (previous) => previous,
  });
}

export function useCurrentSchool() {
  return useQuery({
    queryKey: queryKeys.schools.current,
    queryFn: () => schoolsApi.current(),
    // Super admins have no own school; a 404 here is expected, not an error
    // worth retrying.
    retry: false,
  });
}

export function useCreateSchool() {
  const m = useCatalog(adminMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SchoolCreate) => schoolsApi.create(body),
    onSuccess: (school) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.schools.all });
      toast.success(m.schoolOnboarded, fill(m.schoolOnboardedBody, { name: school.name }));
    },
    onError: (error) => toast.error(m.schoolOnboardFailed, errorMessage(error)),
  });
}

export function useUpdateSchool() {
  const m = useCatalog(adminMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: SchoolUpdate }) => schoolsApi.update(id, body),
    onSuccess: (school) => {
      queryClient.setQueryData(queryKeys.schools.detail(school.id), school);
      void queryClient.invalidateQueries({ queryKey: queryKeys.schools.all });
      toast.success(m.schoolUpdated);
    },
    onError: (error) => toast.error(m.schoolUpdateFailed, errorMessage(error)),
  });
}

export function useApproveSchool() {
  const m = useCatalog(adminMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => schoolsApi.approve(id),
    onSuccess: (school) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.schools.all });
      toast.success(m.schoolApproved, fill(m.schoolApprovedBody, { name: school.name }));
    },
    onError: (error) => toast.error(m.schoolApproveFailed, errorMessage(error)),
  });
}

export function useSuspendSchool() {
  const m = useCatalog(adminMessages).toast;
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => schoolsApi.suspend(id),
    onSuccess: (school) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.schools.all });
      toast.success(m.schoolSuspended, fill(m.schoolSuspendedBody, { name: school.name }));
    },
    onError: (error) => toast.error(m.schoolSuspendFailed, errorMessage(error)),
  });
}
