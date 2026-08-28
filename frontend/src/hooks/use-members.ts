"use client";

import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/lib/api/query-keys";
import { members as membersApi } from "@/lib/api/resources";

/**
 * The active branch's teaching staff, for the teacher pickers.
 *
 * `staleTime` is generous on purpose. Staff lists change when someone is hired, which
 * is a thing that happens a few times a term -- not a thing that happens while a
 * dialog is open. Refetching this on every mount would put a request behind every
 * "Edit section" click to re-learn a list that has not moved since breakfast.
 *
 * `enabled` guards the null branch id rather than the caller doing it: a component
 * that has not resolved its school yet should render the picker in a loading state,
 * not fire `GET /schools/null/teachers`.
 */
export function useTeachers(schoolId: string | null) {
  return useQuery({
    queryKey: queryKeys.members.teachers(schoolId ?? ""),
    queryFn: () => membersApi.teachers(schoolId as string),
    enabled: Boolean(schoolId),
    staleTime: 5 * 60 * 1000,
  });
}
