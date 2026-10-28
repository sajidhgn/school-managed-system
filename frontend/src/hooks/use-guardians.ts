"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { queryKeys } from "@/lib/api/query-keys";
import { errorMessage } from "@/lib/api/errors";
import { guardiansApi } from "@/lib/api/resources/guardians";
import type { GuardianPortalGrant } from "@/lib/api/types";

export function useStudentGuardians(studentId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.guardians.forStudent(studentId),
    queryFn: () => guardiansApi.forStudent(studentId),
    enabled: enabled && Boolean(studentId),
  });
}

export function useGrantPortalAccess(studentId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: GuardianPortalGrant) => guardiansApi.grantPortalAccess(studentId, body),
    onSuccess: (card, body) => {
      queryClient.setQueryData(queryKeys.guardians.forStudent(studentId), card);
      toast.success("Parent portal on", `${body.full_name} can now sign in with ${body.phone}.`);
    },
    onError: (error) => toast.error("Couldn't turn on the parent portal", errorMessage(error)),
  });
}

export function useSetChildPortalAccess(studentId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ guardianId, canView }: { guardianId: string; canView: boolean }) =>
      guardiansApi.setChildPortalAccess(guardianId, studentId, canView),
    onSuccess: (_, { canView }) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.guardians.forStudent(studentId),
      });
      toast.success(canView ? "Parent portal on" : "Parent portal off");
    },
    onError: (error) => toast.error("Couldn't change portal access", errorMessage(error)),
  });
}
