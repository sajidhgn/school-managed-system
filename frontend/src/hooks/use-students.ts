"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { queryKeys } from "@/lib/api/query-keys";
import { errorMessage } from "@/lib/api/errors";
import { studentsApi, type StudentListParams } from "@/lib/api/resources/students";
import type { StudentCreate, StudentUpdate } from "@/lib/api/types";

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
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: StudentCreate) => studentsApi.create(body),
    onSuccess: (student) => {
      // Invalidate the whole subtree: a new student can land on any page of
      // any filter combination.
      void queryClient.invalidateQueries({ queryKey: queryKeys.students.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.summary });
      toast.success("Student enrolled", `${student.full_name} was added.`);
    },
    onError: (error) => toast.error("Couldn't enroll student", errorMessage(error)),
  });
}

export function useUpdateStudent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: StudentUpdate }) =>
      studentsApi.update(id, body),
    onSuccess: (student) => {
      queryClient.setQueryData(queryKeys.students.detail(student.id), student);
      void queryClient.invalidateQueries({ queryKey: queryKeys.students.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.summary });
      toast.success("Changes saved", `${student.full_name} was updated.`);
    },
    onError: (error) => toast.error("Couldn't save changes", errorMessage(error)),
  });
}

export function useDeleteStudent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => studentsApi.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.students.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.classes.summary });
      toast.success("Student removed");
    },
    onError: (error) => toast.error("Couldn't remove student", errorMessage(error)),
  });
}
