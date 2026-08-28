import { api } from "@/lib/api/client";
import type {
  ClassSubjectCreate,
  ClassSubjectRead,
  ClassSubjectUpdate,
  Page,
  PageParams,
  SubjectCreate,
  SubjectRead,
  SubjectUpdate,
} from "@/lib/api/types";

/** Mirrors backend/app/modules/academics/router.py (`subjects_router` + curriculum). */

export interface SubjectListParams extends PageParams {
  q?: string | null;
}

export const subjectsApi = {
  list: (params: SubjectListParams = {}) =>
    api.get<Page<SubjectRead>>("/subjects", { params: { ...params } }),

  get: (id: string) => api.get<SubjectRead>(`/subjects/${id}`),

  /** `code` is upper-cased server-side, so "math" and "MATH" cannot both exist. */
  create: (body: SubjectCreate) => api.post<SubjectRead>("/subjects", body),

  update: (id: string, body: SubjectUpdate) => api.patch<SubjectRead>(`/subjects/${id}`, body),

  /** 409s while any class still studies the subject, naming how many. */
  remove: (id: string) => api.delete<void>(`/subjects/${id}`),

  /**
   * Which subjects a CLASS studies.
   *
   * Keyed on the class, not the section: "Grade 10 studies Physics" is a curriculum
   * decision, while "10-B's Physics is taught by Mrs Khan" is a timetable one.
   */
  curriculum: {
    list: (classId: string) => api.get<ClassSubjectRead[]>(`/classes/${classId}/subjects`),

    add: (classId: string, body: ClassSubjectCreate) =>
      api.post<ClassSubjectRead>(`/classes/${classId}/subjects`, body),

    update: (linkId: string, body: ClassSubjectUpdate) =>
      api.patch<ClassSubjectRead>(`/classes/curriculum/${linkId}`, body),

    remove: (linkId: string) => api.delete<void>(`/classes/curriculum/${linkId}`),
  },
};
