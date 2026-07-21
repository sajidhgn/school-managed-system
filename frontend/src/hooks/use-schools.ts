"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { queryKeys } from "@/lib/api/query-keys";
import { errorMessage } from "@/lib/api/errors";
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
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SchoolCreate) => schoolsApi.create(body),
    onSuccess: (school) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.schools.all });
      toast.success("School onboarded", `${school.name} was created.`);
    },
    onError: (error) => toast.error("Couldn't onboard school", errorMessage(error)),
  });
}

export function useUpdateSchool() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: SchoolUpdate }) => schoolsApi.update(id, body),
    onSuccess: (school) => {
      queryClient.setQueryData(queryKeys.schools.detail(school.id), school);
      void queryClient.invalidateQueries({ queryKey: queryKeys.schools.all });
      toast.success("School updated");
    },
    onError: (error) => toast.error("Couldn't update school", errorMessage(error)),
  });
}

export function useApproveSchool() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => schoolsApi.approve(id),
    onSuccess: (school) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.schools.all });
      toast.success("School approved", `${school.name} is now active.`);
    },
    onError: (error) => toast.error("Couldn't approve school", errorMessage(error)),
  });
}

export function useSuspendSchool() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => schoolsApi.suspend(id),
    onSuccess: (school) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.schools.all });
      toast.success("School suspended", `${school.name} can no longer sign in.`);
    },
    onError: (error) => toast.error("Couldn't suspend school", errorMessage(error)),
  });
}
