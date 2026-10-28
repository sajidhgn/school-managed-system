import { api } from "@/lib/api/client";
import type { GuardianPortalGrant, StudentGuardianRead } from "@/lib/api/types";

/** Mirrors the staff half of backend/app/modules/guardians/router.py. */
export const guardiansApi = {
  forStudent: (studentId: string) =>
    api.get<StudentGuardianRead[]>(`/guardians/students/${studentId}`),

  /**
   * Register the phone if needed and link it to the student with portal access.
   * Idempotent; returns the student's updated contact card.
   */
  grantPortalAccess: (studentId: string, body: GuardianPortalGrant) =>
    api.post<StudentGuardianRead[]>(`/guardians/students/${studentId}/portal-access`, body),

  /** Per child: `false` keeps the contact but hides this child from their portal. */
  setChildPortalAccess: (guardianId: string, studentId: string, canView: boolean) =>
    api.patch(`/guardians/${guardianId}/students/${studentId}`, {
      can_view_results: canView,
    }),
};
