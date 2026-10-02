import { api } from "@/lib/api/client";
import type { DiaryPage, DiaryPageWrite, DiarySectionOption } from "@/lib/api/types";

/** Mirrors backend/app/modules/diary/router.py. `date` is an ISO day (YYYY-MM-DD). */
export const diaryApi = {
  /** Every section, the caller's own classes first, with what they may write. */
  sections: (date: string) =>
    api.get<DiarySectionOption[]>("/diary/sections", { params: { date } }),

  page: (sectionId: string, date: string) =>
    api.get<DiaryPage>(`/diary/sections/${sectionId}`, { params: { date } }),

  /** Partial: only the rows named are changed; blank content clears a row. */
  save: (sectionId: string, date: string, body: DiaryPageWrite) =>
    api.put<DiaryPage>(`/diary/sections/${sectionId}`, body, { params: { date } }),
};
