import { api } from "@/lib/api/client";
import type {
  AttendanceEntryInput,
  AttendanceSessionDetail,
  AttendanceSessionOpen,
  AttendanceSessionRead,
  AttendanceSessionStatus,
  DailyOverview,
  Page,
  PageParams,
  SectionAttendanceReport,
  StudentAttendanceSummary,
} from "@/lib/api/types";

/** Mirrors backend/app/modules/attendance/router.py. */

export interface SessionListParams extends PageParams {
  section_id?: string | null;
  from_date?: string | null;
  to_date?: string | null;
  status?: AttendanceSessionStatus | null;
}

export interface DateRange {
  from_date: string;
  to_date: string;
}

export const attendanceApi = {
  /**
   * Every section and whether its register has been taken — the morning chase list.
   *
   * `session_id: null` means nobody opened that section's register, which is a
   * distinct state from "everyone was present". Rendering them the same way is the
   * mistake the backend's session table exists to prevent.
   */
  today: (date?: string) => api.get<DailyOverview>("/attendance/today", { params: { date } }),

  list: (params: SessionListParams = {}) =>
    api.get<Page<AttendanceSessionRead>>("/attendance", { params: { ...params } }),

  get: (id: string) => api.get<AttendanceSessionDetail>(`/attendance/${id}`),

  /**
   * Open a register, pre-filled `present` from the section's roster.
   *
   * IDEMPOTENT: opening one that already exists returns it rather than conflicting,
   * so a double tap on a slow connection is safe and needs no client-side guard.
   */
  open: (body: AttendanceSessionOpen) =>
    api.post<AttendanceSessionDetail>("/attendance", body),

  /**
   * Set statuses for SOME of the students — send only what changed.
   *
   * On a submitted register this is an amendment: it needs `attendance:amend` and a
   * `reason`, and writes one audit row per changed student.
   */
  mark: (id: string, entries: AttendanceEntryInput[], reason?: string) =>
    api.patch<AttendanceSessionDetail>(`/attendance/${id}/entries`, { entries, reason }),

  submit: (id: string) => api.post<AttendanceSessionDetail>(`/attendance/${id}/submit`),

  /** `attendance:amend` only. The reason is required and lands in the audit trail. */
  reopen: (id: string, reason: string) =>
    api.post<AttendanceSessionDetail>(`/attendance/${id}/reopen`, { reason }),

  /** Drafts only — a submitted register is corrected by amendment, never deleted. */
  discard: (id: string) => api.delete<void>(`/attendance/${id}`),

  /**
   * `percentage` is null — not 0 — when nothing countable exists in the range.
   * Render that as "no data", never as a 0% that reads like a disciplinary figure.
   */
  studentSummary: (studentId: string, range: DateRange) =>
    api.get<StudentAttendanceSummary>(`/attendance/students/${studentId}/summary`, {
      params: { ...range },
    }),

  sectionReport: (sectionId: string, range: DateRange) =>
    api.get<SectionAttendanceReport>(`/attendance/sections/${sectionId}/report`, {
      params: { ...range },
    }),
};
