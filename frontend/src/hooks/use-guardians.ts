"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { queryKeys } from "@/lib/api/query-keys";
import { errorMessage } from "@/lib/api/errors";
import { guardiansApi } from "@/lib/api/resources/guardians";
import { fill } from "@/lib/i18n/format";
import { ltr } from "@/lib/i18n/modules/students";
import { studentsGuardiansMessages } from "@/lib/i18n/modules/students-guardians";
import { useCatalog } from "@/lib/i18n/use-catalog";
import type {
  GuardianLinkCreate,
  GuardianLinkUpdate,
  GuardianPortalGrant,
  GuardianUpdate,
} from "@/lib/api/types";

export function useStudentGuardians(studentId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.guardians.forStudent(studentId),
    queryFn: () => guardiansApi.forStudent(studentId),
    enabled: enabled && Boolean(studentId),
  });
}

export function useGrantPortalAccess(studentId: string) {
  const m = useCatalog(studentsGuardiansMessages).toast;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: GuardianPortalGrant) => guardiansApi.grantPortalAccess(studentId, body),
    onSuccess: (card, body) => {
      queryClient.setQueryData(queryKeys.guardians.forStudent(studentId), card);
      toast.success(
        m.portalOn,
        fill(m.portalOnBody, { name: body.full_name, phone: ltr(body.phone) }),
      );
    },
    onError: (error) => toast.error(m.portalOnFailed, errorMessage(error)),
  });
}

export function useSetChildPortalAccess(studentId: string) {
  const m = useCatalog(studentsGuardiansMessages).toast;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ guardianId, canView }: { guardianId: string; canView: boolean }) =>
      guardiansApi.setChildPortalAccess(guardianId, studentId, canView),
    onSuccess: (_, { canView }) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.guardians.forStudent(studentId),
      });
      toast.success(canView ? m.portalOn : m.portalOff);
    },
    onError: (error) => toast.error(m.accessFailed, errorMessage(error)),
  });
}

/** One guardian with every child they are linked to. Fetched when the editor opens. */
export function useGuardianDetail(guardianId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.guardians.detail(guardianId),
    queryFn: () => guardiansApi.get(guardianId),
    enabled: enabled && Boolean(guardianId),
  });
}

/**
 * Every guardian mutation refreshes the whole guardian cache, and the student list:
 * a phone or a link edited on one child's page also shows on their siblings' pages,
 * and a sibling link changes the family the fee module discounts.
 */
function useGuardianMutation<TArgs, TResult>(
  fn: (args: TArgs) => Promise<TResult>,
  messages: { success: (args: TArgs) => [string, string?]; failure: string },
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (_, args) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.guardians.all });
      const [title, body] = messages.success(args);
      toast.success(title, body);
    },
    onError: (error) => toast.error(messages.failure, errorMessage(error)),
  });
}

export function useUpdateGuardian() {
  const m = useCatalog(studentsGuardiansMessages).toast;
  return useGuardianMutation(
    ({ guardianId, body }: { guardianId: string; body: GuardianUpdate }) =>
      guardiansApi.update(guardianId, body),
    { success: () => [m.detailsSaved], failure: m.detailsFailed },
  );
}

export function useChangeGuardianPhone() {
  const m = useCatalog(studentsGuardiansMessages).toast;
  return useGuardianMutation(
    ({ guardianId, phone }: { guardianId: string; phone: string }) =>
      guardiansApi.changePhone(guardianId, phone),
    {
      success: ({ phone }) => [m.phoneChanged, fill(m.phoneChangedBody, { phone: ltr(phone) })],
      failure: m.phoneFailed,
    },
  );
}

export function useSetGuardianPortal() {
  const m = useCatalog(studentsGuardiansMessages).toast;
  return useGuardianMutation(
    ({ guardianId, enabled }: { guardianId: string; enabled: boolean }) =>
      guardiansApi.setPortal(guardianId, enabled),
    {
      success: ({ enabled }) => [
        enabled ? m.portalOpened : m.portalClosed,
        enabled ? undefined : m.portalClosedBody,
      ],
      failure: m.accessFailed,
    },
  );
}

export function useUpdateGuardianLink() {
  const m = useCatalog(studentsGuardiansMessages).toast;
  return useGuardianMutation(
    ({
      guardianId,
      studentId,
      body,
    }: {
      guardianId: string;
      studentId: string;
      body: GuardianLinkUpdate;
    }) => guardiansApi.updateLink(guardianId, studentId, body),
    { success: () => [m.saved], failure: m.relationshipFailed },
  );
}

export function useLinkGuardian() {
  const m = useCatalog(studentsGuardiansMessages).toast;
  return useGuardianMutation(
    ({ guardianId, body }: { guardianId: string; body: GuardianLinkCreate; studentName: string }) =>
      guardiansApi.link(guardianId, body),
    {
      success: ({ studentName }) => [m.linked, fill(m.linkedBody, { name: studentName })],
      failure: m.linkFailed,
    },
  );
}

/**
 * Take a parent off one child, and — when that was their last child here and the
 * caller may — remove the record too. The API refuses to delete a record with
 * children still linked, so the order is fixed: unlink, then remove.
 */
export function useUnlinkGuardian() {
  const m = useCatalog(studentsGuardiansMessages).toast;
  return useGuardianMutation(
    async ({
      guardianId,
      studentId,
      removeRecord,
    }: {
      guardianId: string;
      studentId: string;
      removeRecord: boolean;
    }) => {
      await guardiansApi.unlink(guardianId, studentId);
      if (removeRecord) await guardiansApi.remove(guardianId);
    },
    {
      success: ({ removeRecord }) => [
        removeRecord ? m.parentRemoved : m.removedFromStudent,
        removeRecord ? undefined : m.removedFromStudentBody,
      ],
      failure: m.removeFailed,
    },
  );
}
