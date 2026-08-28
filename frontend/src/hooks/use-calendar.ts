"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { calendarApi } from "@/lib/api/resources/calendar";
import type {
  AcademicYearCreate,
  AcademicYearUpdate,
  PageParams,
  TermCreate,
  TermUpdate,
} from "@/lib/api/types";

export function useAcademicYears(params: PageParams = {}) {
  return useQuery({
    queryKey: queryKeys.calendar.years(params),
    queryFn: () => calendarApi.years.list(params),
    placeholderData: (previous) => previous,
  });
}

/**
 * The year new work defaults to, or `null` if the school has not set one.
 *
 * `NO_CURRENT_ACADEMIC_YEAR` is a SETUP PROMPT, not a failure: a school that has
 * not built its calendar yet is in a normal state, and surfacing a red error
 * banner on every screen that needs a year would be wrong. It is mapped to `null`
 * here so callers branch on data rather than on an error object; anything else is
 * rethrown and handled as a real failure.
 */
export function useCurrentAcademicYear() {
  return useQuery({
    queryKey: queryKeys.calendar.current,
    queryFn: async () => {
      try {
        return await calendarApi.years.current();
      } catch (error) {
        if (error instanceof ApiError && error.code === "NO_CURRENT_ACADEMIC_YEAR") return null;
        throw error;
      }
    },
  });
}

export function useTerms(yearId: string | null) {
  return useQuery({
    queryKey: queryKeys.calendar.terms(yearId ?? ""),
    queryFn: () => calendarApi.terms.list(yearId as string),
    enabled: Boolean(yearId),
  });
}

export function useCreateAcademicYear() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AcademicYearCreate) => calendarApi.years.create(body),
    onSuccess: (year) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.calendar.all });
      toast.success("Academic year created", year.name);
    },
    onError: (error) => toast.error("Couldn't create the year", errorMessage(error)),
  });
}

export function useUpdateAcademicYear() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: AcademicYearUpdate }) =>
      calendarApi.years.update(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.calendar.all });
      toast.success("Academic year updated");
    },
    onError: (error) => toast.error("Couldn't update the year", errorMessage(error)),
  });
}

/**
 * Promoting a year DEMOTES the incumbent, so the whole calendar subtree is
 * invalidated rather than just the promoted row — two records changed and only one
 * of them is named.
 */
export function useSetCurrentYear() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => calendarApi.years.setCurrent(id),
    onSuccess: (year) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.calendar.all });
      toast.success("Current year set", `New work now defaults to ${year.name}.`);
    },
    onError: (error) => toast.error("Couldn't set the current year", errorMessage(error)),
  });
}

/** The backend 409s while terms or enrollments remain; the message is surfaced as-is. */
export function useDeleteAcademicYear() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => calendarApi.years.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.calendar.all });
      toast.success("Academic year deleted");
    },
    onError: (error) => toast.error("Couldn't delete the year", errorMessage(error)),
  });
}

export function useCreateTerm() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ yearId, body }: { yearId: string; body: TermCreate }) =>
      calendarApi.terms.create(yearId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.calendar.all });
      toast.success("Term added");
    },
    onError: (error) => toast.error("Couldn't add the term", errorMessage(error)),
  });
}

export function useUpdateTerm() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ termId, body }: { termId: string; body: TermUpdate }) =>
      calendarApi.terms.update(termId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.calendar.all });
      toast.success("Term updated");
    },
    onError: (error) => toast.error("Couldn't update the term", errorMessage(error)),
  });
}

export function useDeleteTerm() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (termId: string) => calendarApi.terms.remove(termId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.calendar.all });
      toast.success("Term deleted");
    },
    onError: (error) => toast.error("Couldn't delete the term", errorMessage(error)),
  });
}

/**
 * Open enrollment history for students who predate the calendar.
 *
 * Idempotent server-side, so a double-click is harmless. The result is reported
 * in full — including `unplaced`, which is the number the registrar still has to
 * act on and would otherwise go unnoticed.
 */
export function useBackfillEnrollments() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (yearId: string) => calendarApi.years.backfillEnrollments(yearId),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.students.all });
      toast.success(
        "Enrollment history opened",
        `${result.opened} opened, ${result.already_enrolled} already on file, ` +
          `${result.unplaced} still need a section.`,
      );
    },
    onError: (error) => toast.error("Couldn't open enrollment history", errorMessage(error)),
  });
}
