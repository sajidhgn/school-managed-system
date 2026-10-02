"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { diaryApi } from "@/lib/api/resources/diary";
import type { DiaryPageWrite } from "@/lib/api/types";

export function useDiarySections(date: string) {
  return useQuery({
    queryKey: queryKeys.diary.sections(date),
    queryFn: () => diaryApi.sections(date),
    placeholderData: (previous) => previous,
  });
}

export function useDiaryPage(sectionId: string | null, date: string) {
  return useQuery({
    queryKey: queryKeys.diary.page(sectionId ?? "", date),
    queryFn: () => diaryApi.page(sectionId as string, date),
    enabled: Boolean(sectionId),
  });
}

export function useSaveDiary() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      sectionId,
      date,
      body,
    }: {
      sectionId: string;
      date: string;
      body: DiaryPageWrite;
    }) => diaryApi.save(sectionId, date, body),
    onSuccess: (page, { sectionId, date }) => {
      // The response IS the saved page, so write it straight into the cache rather
      // than refetching what was just returned; the picker's filled counts change too.
      queryClient.setQueryData(queryKeys.diary.page(sectionId, date), page);
      void queryClient.invalidateQueries({ queryKey: queryKeys.diary.sections(date) });
      toast.success("Diary saved");
    },
    onError: (error) => toast.error("Couldn't save the diary", errorMessage(error)),
  });
}
