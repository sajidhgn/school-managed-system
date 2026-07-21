import { api } from "@/lib/api/client";
import type {
  ClassCreate,
  ClassRead,
  ClassSummary,
  ClassUpdate,
  Page,
  PageParams,
  SectionCreate,
  SectionRead,
  SectionUpdate,
} from "@/lib/api/types";

/** Mirrors backend/app/modules/academics/router.py. */

export const classesApi = {
  list: (params: PageParams = {}) =>
    api.get<Page<ClassRead>>("/classes", { params: { ...params } }),

  /** Classes with section and headcount rollups — what the dashboard renders. */
  summary: () => api.get<ClassSummary[]>("/classes/summary"),

  get: (id: string) => api.get<ClassRead>(`/classes/${id}`),

  create: (body: ClassCreate) => api.post<ClassRead>("/classes", body),

  update: (id: string, body: ClassUpdate) => api.patch<ClassRead>(`/classes/${id}`, body),

  /** Backend rejects this with a 409 unless the class is empty. */
  remove: (id: string) => api.delete<void>(`/classes/${id}`),

  sections: {
    list: (classId: string) => api.get<SectionRead[]>(`/classes/${classId}/sections`),

    create: (classId: string, body: SectionCreate) =>
      api.post<SectionRead>(`/classes/${classId}/sections`, body),

    update: (sectionId: string, body: SectionUpdate) =>
      api.patch<SectionRead>(`/classes/sections/${sectionId}`, body),

    /** Also 409s while students are still assigned to the section. */
    remove: (sectionId: string) => api.delete<void>(`/classes/sections/${sectionId}`),
  },
};
