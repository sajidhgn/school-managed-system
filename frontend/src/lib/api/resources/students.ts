import { api, publicRequest } from "@/lib/api/client";
import type {
  AdmissionResponse,
  Page,
  PageParams,
  StudentAdmissionRequest,
  StudentCreate,
  StudentRead,
  StudentStatus,
  StudentUpdate,
} from "@/lib/api/types";

/** Mirrors backend/app/modules/students/router.py. */

export interface StudentListParams extends PageParams {
  q?: string | null;
  section_id?: string | null;
  status?: StudentStatus | null;
}

export const studentsApi = {
  list: (params: StudentListParams = {}) =>
    api.get<Page<StudentRead>>("/students", { params: { ...params } }),

  get: (id: string) => api.get<StudentRead>(`/students/${id}`),

  create: (body: StudentCreate) => api.post<StudentRead>("/students", body),

  update: (id: string, body: StudentUpdate) => api.patch<StudentRead>(`/students/${id}`, body),

  remove: (id: string) => api.delete<void>(`/students/${id}`),
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
