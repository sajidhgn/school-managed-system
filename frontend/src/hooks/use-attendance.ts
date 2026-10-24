"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import {
  attendanceApi,
  type AnalyticsParams,
  type DateRange,
  type StudentAttendanceParams,
} from "@/lib/api/resources/attendance";
import type { AttendanceEntryInput, AttendanceSessionOpen } from "@/lib/api/types";

/**
 * The morning chase list: every section and whether its register has been taken.
 *
 * Polled on a slow interval rather than left static. Registers are submitted by
 * several teachers at once during the first half-hour of the day, and a head
 * teacher watching this screen should see it drain without reloading. Sixty
 * seconds is well under the time it takes anyone to act on a missing register and
 * well over anything that would look like a spinner storm.
 */
export function useDailyOverview(date?: string) {
  return useQuery({
    queryKey: queryKeys.attendance.today(date ?? null),
    queryFn: () => attendanceApi.today(date),
    refetchInterval: 60_000,
  });
}

export function useAttendanceSession(sessionId: string | null) {
  return useQuery({
    queryKey: queryKeys.attendance.session(sessionId ?? ""),
    queryFn: () => attendanceApi.get(sessionId as string),
    enabled: Boolean(sessionId),
  });
}

/**
 * Open a register for a section.
 *
 * The backend is idempotent here — opening one that already exists returns it —
 * so this doubles as "continue where I left off" and the UI needs no separate
 * branch for the two cases.
 */
export function useOpenRegister() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AttendanceSessionOpen) => attendanceApi.open(body),
    onSuccess: (session) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.attendance.all });
      queryClient.setQueryData(queryKeys.attendance.session(session.id), session);
    },
    onError: (error) => toast.error("Couldn't open the register", errorMessage(error)),
  });
}

/**
 * Set statuses for the students that changed.
 *
 * `reason` is required by the backend only when the register has been submitted,
 * where this becomes an audited amendment. Passing it always would be harmless;
 * the caller passes it only when amending so the draft path stays a plain edit.
 */
export function useMarkAttendance() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      sessionId,
      entries,
      reason,
    }: {
      sessionId: string;
      entries: AttendanceEntryInput[];
      reason?: string;
    }) => attendanceApi.mark(sessionId, entries, reason),
    onSuccess: (session) => {
      queryClient.setQueryData(queryKeys.attendance.session(session.id), session);
      void queryClient.invalidateQueries({ queryKey: queryKeys.attendance.all });
    },
    onError: (error) => toast.error("Couldn't save attendance", errorMessage(error)),
  });
}

export function useSubmitRegister() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) => attendanceApi.submit(sessionId),
    onSuccess: (session) => {
      queryClient.setQueryData(queryKeys.attendance.session(session.id), session);
      void queryClient.invalidateQueries({ queryKey: queryKeys.attendance.all });
      toast.success(
        "Register submitted",
        `${session.present_count} present, ${session.absent_count} absent.`,
      );
    },
    onError: (error) => toast.error("Couldn't submit the register", errorMessage(error)),
  });
}

/** `attendance:amend` only. The reason is required and lands in the audit trail. */
export function useReopenRegister() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, reason }: { sessionId: string; reason: string }) =>
      attendanceApi.reopen(sessionId, reason),
    onSuccess: (session) => {
      queryClient.setQueryData(queryKeys.attendance.session(session.id), session);
      void queryClient.invalidateQueries({ queryKey: queryKeys.attendance.all });
      toast.success("Register reopened", "Your correction will be recorded in the audit log.");
    },
    onError: (error) => toast.error("Couldn't reopen the register", errorMessage(error)),
  });
}

export function useStudentAttendance(studentId: string | null, range: DateRange) {
  return useQuery({
    queryKey: queryKeys.attendance.studentSummary(
      studentId ?? "",
      range.from_date,
      range.to_date,
    ),
    queryFn: () => attendanceApi.studentSummary(studentId as string, range),
    enabled: Boolean(studentId),
  });
}

export function useSectionAttendance(sectionId: string | null, range: DateRange) {
  return useQuery({
    queryKey: queryKeys.attendance.sectionReport(
      sectionId ?? "",
      range.from_date,
      range.to_date,
    ),
    queryFn: () => attendanceApi.sectionReport(sectionId as string, range),
    enabled: Boolean(sectionId),
  });
}

/**
 * The class-by-class analytics.
 *
 * `placeholderData` keeps the previous range on screen while a new one loads, so
 * changing the date range or the class dims the page instead of flashing it back to
 * skeletons — every chart and number below the filters holds its frame until the new
 * slice arrives.
 */
export function useAttendanceAnalytics(params: AnalyticsParams) {
  return useQuery({
    queryKey: queryKeys.attendance.analytics(params),
    queryFn: () => attendanceApi.analytics(params),
    placeholderData: (previous) => previous,
  });
}

/** Every student's attendance, one page at a time. Same frame-holding as above. */
export function useStudentAttendanceList(params: StudentAttendanceParams) {
  return useQuery({
    queryKey: queryKeys.attendance.students(params),
    queryFn: () => attendanceApi.students(params),
    placeholderData: (previous) => previous,
  });
}

/**
 * One student's calendar for the academic year so far.
 *
 * One request for the whole year rather than one per month: the drill-down pages
 * through months client-side, and the server already returns a rate per month, so
 * flipping back and forth costs nothing.
 */
export function useStudentAttendanceCalendar(studentId: string | null) {
  return useQuery({
    queryKey: queryKeys.attendance.calendar(studentId ?? "", null, null),
    queryFn: () => attendanceApi.studentCalendar(studentId as string),
    enabled: Boolean(studentId),
  });
}
