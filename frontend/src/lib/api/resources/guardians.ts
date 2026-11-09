import { api } from "@/lib/api/client";
import type {
  GuardianDetail,
  GuardianLinkCreate,
  GuardianLinkUpdate,
  GuardianPortalGrant,
  GuardianRead,
  GuardianUpdate,
  LinkedStudentRead,
  StudentGuardianRead,
} from "@/lib/api/types";

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

  /** The record with every child it is linked to, across campuses. */
  get: (guardianId: string) => api.get<GuardianDetail>(`/guardians/${guardianId}`),

  /** Name, email, CNIC and the rest. NOT the sign-in phone — see `changePhone`. */
  update: (guardianId: string, body: GuardianUpdate) =>
    api.patch<GuardianRead>(`/guardians/${guardianId}`, body),

  /** `guardian:portal`. A credential change: whoever holds the new number signs in. */
  changePhone: (guardianId: string, phone: string) =>
    api.put<GuardianRead>(`/guardians/${guardianId}/phone`, { phone }),

  /** `guardian:portal`. Closes this organization's portal only. */
  setPortal: (guardianId: string, enabled: boolean) =>
    api.put<GuardianRead>(`/guardians/${guardianId}/portal`, { enabled }),

  /** 409 while any child is still linked — unlink first, deliberately. */
  remove: (guardianId: string) => api.delete<void>(`/guardians/${guardianId}`),

  link: (guardianId: string, body: GuardianLinkCreate) =>
    api.post<LinkedStudentRead>(`/guardians/${guardianId}/students`, body),

  updateLink: (guardianId: string, studentId: string, body: GuardianLinkUpdate) =>
    api.patch<LinkedStudentRead>(`/guardians/${guardianId}/students/${studentId}`, body),

  unlink: (guardianId: string, studentId: string) =>
    api.delete<void>(`/guardians/${guardianId}/students/${studentId}`),
};
