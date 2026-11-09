"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { queryKeys } from "@/lib/api/query-keys";
import { errorMessage } from "@/lib/api/errors";
import { studentsApi, type StudentListParams } from "@/lib/api/resources/students";
import type { StudentCreate, StudentUpdate } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { studentsMessages } from "@/lib/i18n/modules/students";
import { useCatalog } from "@/lib/i18n/use-catalog";

export function useStudents(params: StudentListParams) {
  return useQuery({
    queryKey: queryKeys.students.list(params),
    queryFn: () => studentsApi.list(params),
    // Keeps the previous page visible while the next one loads, so the table
    // doesn't collapse to a skeleton on every keystroke or page change.
    placeholderData: (previous) => previous,
  });
}

export function useStudent(id: string) {
  return useQuery({
    queryKey: queryKeys.students.detail(id),
    queryFn: () => studentsApi.get(id),
    enabled: Boolean(id),
  });
}

export function useCreateStudent() {
  const m = useCatalog(studentsMessages).toast;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: StudentCreate) => studentsApi.create(body),
    onSuccess: (student) => {
      // Invalidate the whole subtree: a new student can land on any page of
      // any filter combination.
      void queryClient.invalidateQueries({ queryKey: queryKeys.students.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.summary });
      toast.success(m.enrolled, fill(m.enrolledBody, { name: student.full_name }));
    },
    onError: (error) => toast.error(m.enrollFailed, errorMessage(error)),
  });
}

export function useUpdateStudent() {
  const m = useCatalog(studentsMessages).toast;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: StudentUpdate }) =>
      studentsApi.update(id, body),
    onSuccess: (student) => {
      queryClient.setQueryData(queryKeys.students.detail(student.id), student);
      void queryClient.invalidateQueries({ queryKey: queryKeys.students.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.summary });
      toast.success(m.saved, fill(m.savedBody, { name: student.full_name }));
    },
    onError: (error) => toast.error(m.saveFailed, errorMessage(error)),
  });
}

export function useDeleteStudent() {
  const m = useCatalog(studentsMessages).toast;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => studentsApi.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.students.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.summary });
      toast.success(m.removed);
    },
    onError: (error) => toast.error(m.removeFailed, errorMessage(error)),
  });
}

/**
 * Accept an application: PENDING → ACTIVE, optionally seated in a section.
 *
 * This is the moment the child takes a plan seat (a pending application takes none),
 * so a full plan answers 402 here and the toast carries the API's reason. A full
 * section answers 409 the same way.
 */
export function useAdmitApplicant() {
  const m = useCatalog(studentsMessages).toast;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      sectionId,
      enrolledOn,
    }: {
      id: string;
      sectionId: string | null;
      enrolledOn: string;
    }) =>
      studentsApi.update(id, {
        status: "active",
        enrolled_on: enrolledOn,
        ...(sectionId ? { section_id: sectionId } : {}),
      }),
    onSuccess: (student) => {
      queryClient.setQueryData(queryKeys.students.detail(student.id), student);
      void queryClient.invalidateQueries({ queryKey: queryKeys.students.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.summary });
      toast.success(
        m.admitted,
        student.class_name
          ? fill(m.admittedJoins, {
              name: student.full_name,
              class: `${student.class_name}${student.section_name ? ` · ${student.section_name}` : ""}`,
            })
          : fill(m.admittedNoClass, { name: student.full_name }),
      );
    },
    onError: (error) => toast.error(m.admitFailed, errorMessage(error)),
  });
}

/** Decline an application. A soft delete, like any removal: the record survives for audit. */
export function useDeclineApplicant() {
  const m = useCatalog(studentsMessages).toast;
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => studentsApi.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.students.all });
      toast.success(m.declined);
    },
    onError: (error) => toast.error(m.declineFailed, errorMessage(error)),
  });
}
