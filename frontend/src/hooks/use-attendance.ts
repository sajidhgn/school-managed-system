"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { attendanceApi, type DateRange } from "@/lib/api/resources/attendance";
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
