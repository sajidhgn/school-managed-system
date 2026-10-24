import { api } from "@/lib/api/client";
import type {
  AttendanceEntryInput,
  AttendanceSessionDetail,
  AttendanceSessionOpen,
  AttendanceSessionRead,
  AttendanceAnalytics,
  AttendanceSessionStatus,
  DailyOverview,
  Page,
  PageParams,
  SectionAttendanceReport,
  StudentAttendanceCalendar,
  StudentAttendancePage,
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

/** `GET /attendance/analytics`. Every field optional: the server defaults to the 30
 *  days ending today, a 75% threshold and a five-register minimum. */
export interface AnalyticsParams {
  from_date?: string | null;
  to_date?: string | null;
  class_id?: string | null;
  threshold?: number | null;
  min_sessions?: number | null;
}

/** `GET /attendance/students`. `sort_by` defaults to `overall`, worst first. */
export interface StudentAttendanceParams extends PageParams {
  q?: string | null;
  class_id?: string | null;
  section_id?: string | null;
  from_date?: string | null;
  to_date?: string | null;
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

  /**
   * Every section the caller may see over a range: rates against the previous
   * period of equal length, marking coverage, today's register state, a daily trend,
   * the weekday pattern, the at-risk list, and the today / month / year headline.
   * Counts SUBMITTED WHOLE-DAY registers only.
   */
  analytics: (params: AnalyticsParams = {}) =>
    api.get<AttendanceAnalytics>("/attendance/analytics", { params: { ...params } }),

  /**
   * One row per student: today's line, this month, last month and an overall range.
   *
   * `today_register` is what tells "nobody has marked them yet" apart from "present";
   * `today_status` is set only once the register is submitted.
   */
  students: (params: StudentAttendanceParams = {}) =>
    api.get<StudentAttendancePage>("/attendance/students", { params: { ...params } }),

  /** One student day by day, with a rate per month. Defaults to the academic year. */
  studentCalendar: (studentId: string, range?: Partial<DateRange>) =>
    api.get<StudentAttendanceCalendar>(`/attendance/students/${studentId}/calendar`, {
      params: { ...range },
    }),
};
