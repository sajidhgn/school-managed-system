import { api } from "@/lib/api/client";
import type {
  AcademicYearCreate,
  AcademicYearRead,
  AcademicYearUpdate,
  EnrollmentBackfillResult,
  Page,
  PageParams,
  TermCreate,
  TermRead,
  TermUpdate,
} from "@/lib/api/types";

/** Mirrors backend/app/modules/academics/router.py (`calendar_router`). */

export const calendarApi = {
  years: {
    list: (params: PageParams = {}) =>
      api.get<Page<AcademicYearRead>>("/academic-years", { params: { ...params } }),

    /**
     * The year new work defaults to.
     *
     * 422 with `NO_CURRENT_ACADEMIC_YEAR` when the school has not set one — which
     * is a setup prompt, not an error state. Callers should branch on the code
     * rather than surfacing a generic failure.
     */
    current: () => api.get<AcademicYearRead>("/academic-years/current"),

    get: (id: string) => api.get<AcademicYearRead>(`/academic-years/${id}`),

    create: (body: AcademicYearCreate) => api.post<AcademicYearRead>("/academic-years", body),

    update: (id: string, body: AcademicYearUpdate) =>
      api.patch<AcademicYearRead>(`/academic-years/${id}`, body),

    /**
     * Its own call, not a PATCH field, because promoting one year DEMOTES another.
     * Invalidate the whole `calendar` subtree afterwards — two rows changed.
     */
    setCurrent: (id: string) => api.post<AcademicYearRead>(`/academic-years/${id}/set-current`),

    /** 409s while terms or enrollments still reference the year. */
    remove: (id: string) => api.delete<void>(`/academic-years/${id}`),

    /**
     * One-off catch-up for students who predate the calendar.
     *
     * Idempotent, so a retry after a timeout is safe. Requires `student:promote`,
     * not `calendar:manage`: it writes a row per student.
     */
    backfillEnrollments: (id: string) =>
      api.post<EnrollmentBackfillResult>(`/academic-years/${id}/enrollments/backfill`),
  },

  terms: {
    list: (yearId: string) => api.get<TermRead[]>(`/academic-years/${yearId}/terms`),

    create: (yearId: string, body: TermCreate) =>
      api.post<TermRead>(`/academic-years/${yearId}/terms`, body),

    /** 409s when the dates overlap another term in the same year. */
    update: (termId: string, body: TermUpdate) =>
      api.patch<TermRead>(`/academic-years/terms/${termId}`, body),

    remove: (termId: string) => api.delete<void>(`/academic-years/terms/${termId}`),
  },
};
