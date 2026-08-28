import { api, publicRequest } from "@/lib/api/client";
import type {
  AdmissionResponse,
  EnrollmentPlacement,
  EnrollmentRead,
  FeeStandingFilter,
  Page,
  PageParams,
  PromotionRequest,
  PromotionResult,
  StudentAdmissionRequest,
  StudentCreate,
  StudentListRow,
  StudentRead,
  StudentStatus,
  StudentUpdate,
} from "@/lib/api/types";

/** Mirrors backend/app/modules/students/router.py. */

export interface StudentListParams extends PageParams {
  q?: string | null;
  section_id?: string | null;
  status?: StudentStatus | null;
  /** What the family owes: "pending" | "overdue" | "clear". Server-side, so it
   *  narrows the page count too rather than filtering rows already fetched. */
  fees?: FeeStandingFilter | null;
}

export const studentsApi = {
  list: (params: StudentListParams = {}) =>
    api.get<Page<StudentListRow>>("/students", { params: { ...params } }),

  get: (id: string) => api.get<StudentRead>(`/students/${id}`),

  create: (body: StudentCreate) => api.post<StudentRead>("/students", body),

  update: (id: string, body: StudentUpdate) => api.patch<StudentRead>(`/students/${id}`, body),

  remove: (id: string) => api.delete<void>(`/students/${id}`),

  /**
   * Where this student has sat, newest first.
   *
   * `left_on: null` marks the current placement; there is exactly one such row.
   */
  enrollments: (id: string) => api.get<EnrollmentRead[]>(`/students/${id}/enrollments`),

  /**
   * Seat a student in a section from a given date.
   *
   * The dated form of changing `section_id` through `update` — a registrar
   * recording a transfer that happened last Monday needs somewhere to put the date.
   */
  place: (id: string, body: EnrollmentPlacement) =>
    api.post<EnrollmentRead>(`/students/${id}/enrollments`, body),

  /**
   * Move a section's students into the next academic year.
   *
   * PARTIAL SUCCESS: students who could not be moved come back in `skipped` with a
   * reason rather than failing the batch. Always render that list — a silent
   * `promoted: 28` when 30 were expected is how two children get lost.
   *
   * Requires `student:promote`, which is a separate, dangerous permission.
   */
  promote: (body: PromotionRequest) => api.post<PromotionResult>("/students/promote", body),
};

/**
 * Public admissions submission.
 *
 * Routed through a fixed-purpose anonymous handler. The generic BFF remains closed
 * without a session and cannot be turned into an open proxy.
 */
export const admissionsApi = {
  submit: (body: StudentAdmissionRequest) =>
    publicRequest<AdmissionResponse>("/admissions", body),
};
