import { api } from "@/lib/api/client";
import type {
  Page,
  PageParams,
  SchoolCreate,
  SchoolRead,
  SchoolStatus,
  SchoolUpdate,
} from "@/lib/api/types";

/**
 * Mirrors backend/app/modules/tenancy/router.py.
 *
 * Everything except `current` is guarded by `require_super_admin` upstream —
 * the UI hides these routes for other roles, but the backend is the authority.
 */

export interface SchoolListParams extends PageParams {
  status_filter?: SchoolStatus | null;
}

export const schoolsApi = {
  list: (params: SchoolListParams = {}) =>
    api.get<Page<SchoolRead>>("/schools", { params: { ...params } }),

  /** The caller's own school — available to school admins, not just super admins. */
  current: () => api.get<SchoolRead>("/schools/current"),

  get: (id: string) => api.get<SchoolRead>(`/schools/${id}`),

  create: (body: SchoolCreate) => api.post<SchoolRead>("/schools", body),

  update: (id: string, body: SchoolUpdate) => api.patch<SchoolRead>(`/schools/${id}`, body),

  approve: (id: string) => api.post<SchoolRead>(`/schools/${id}/approve`),

  suspend: (id: string) => api.post<SchoolRead>(`/schools/${id}/suspend`),
};
