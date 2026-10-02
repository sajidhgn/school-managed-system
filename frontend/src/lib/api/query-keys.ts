import type { StructureListParams, VoucherListParams } from "@/lib/api/resources/fees";
import type { SessionListParams } from "@/lib/api/resources/attendance";
import type { ExamListParams } from "@/lib/api/resources/exams";
import type { SubjectListParams } from "@/lib/api/resources/subjects";
import type { StudentListParams } from "@/lib/api/resources/students";
import type { SchoolListParams } from "@/lib/api/resources/schools";
import type { PageParams } from "@/lib/api/types";

/**
 * Centralised TanStack Query keys.
 *
 * Hierarchical so a mutation can invalidate a whole subtree — invalidating
 * `students.all` refreshes every filtered/paginated student list at once.
 */
export const queryKeys = {
  me: ["me"] as const,

  students: {
    all: ["students"] as const,
    list: (params: StudentListParams) => ["students", "list", params] as const,
    detail: (id: string) => ["students", "detail", id] as const,
  },

  classes: {
    all: ["classes"] as const,
    list: (params: PageParams) => ["classes", "list", params] as const,
    detail: (id: string) => ["classes", "detail", id] as const,
    summary: ["classes", "summary"] as const,
    sections: (classId: string) => ["classes", classId, "sections"] as const,
    roster: (sectionId: string) => ["classes", "sections", sectionId, "roster"] as const,
    curriculum: (classId: string) => ["classes", classId, "curriculum"] as const,
  },

  members: {
    all: ["members"] as const,
    // Keyed by branch: a teacher list is only ever meaningful for one campus, and a
    // shared key would serve South Campus's staff to North Campus on a context switch.
    teachers: (schoolId: string) => ["members", schoolId, "teachers"] as const,
  },

  calendar: {
    all: ["calendar"] as const,
    years: (params: PageParams) => ["calendar", "years", params] as const,
    year: (id: string) => ["calendar", "years", "detail", id] as const,
    // Its own key rather than derived from the list: almost every screen needs the
    // current year and nothing else, and making them all subscribe to a paginated
    // list would refetch the whole calendar whenever any year changed.
    current: ["calendar", "current"] as const,
    terms: (yearId: string) => ["calendar", yearId, "terms"] as const,
  },

  subjects: {
    all: ["subjects"] as const,
    list: (params: SubjectListParams) => ["subjects", "list", params] as const,
    detail: (id: string) => ["subjects", "detail", id] as const,
  },

  exams: {
    all: ["exams"] as const,
    list: (params: ExamListParams) => ["exams", "list", params] as const,
    detail: (id: string) => ["exams", "detail", id] as const,
    papers: (examId: string) => ["exams", examId, "papers"] as const,
    marks: (paperId: string) => ["exams", "papers", paperId, "marks"] as const,
    results: (examId: string, classId: string) => ["exams", examId, "results", classId] as const,
  },

  diary: {
    all: ["diary"] as const,
    sections: (date: string) => ["diary", "sections", date] as const,
    page: (sectionId: string, date: string) => ["diary", "page", sectionId, date] as const,
  },

  attendance: {
    all: ["attendance"] as const,
    // The date is part of the key so yesterday's overview stays cached while today's
    // is refetched — a head teacher comparing the two should not evict either.
    today: (date: string | null) => ["attendance", "today", date] as const,
    list: (params: SessionListParams) => ["attendance", "list", params] as const,
    session: (id: string) => ["attendance", "session", id] as const,
    studentSummary: (studentId: string, from: string, to: string) =>
      ["attendance", "student", studentId, from, to] as const,
    sectionReport: (sectionId: string, from: string, to: string) =>
      ["attendance", "section", sectionId, from, to] as const,
  },

  fees: {
    all: ["fees"] as const,
    summary: (year: string, period?: string) => ["fees", "summary", year, period ?? null] as const,
    heads: (params: PageParams) => ["fees", "heads", params] as const,
    structures: (params: StructureListParams) => ["fees", "structures", params] as const,
    structure: (id: string) => ["fees", "structures", "detail", id] as const,
    stationery: (params: PageParams) => ["fees", "stationery", params] as const,
    studentProfile: (studentId: string, year: string) =>
      ["fees", "student-profile", studentId, year] as const,
    vouchers: (params: VoucherListParams) => ["fees", "vouchers", params] as const,
    voucher: (id: string) => ["fees", "vouchers", "detail", id] as const,
    billingSchedule: (year: string) => ["fees", "billing-schedule", year] as const,
  },

  search: {
    all: ["search"] as const,
    // The query string is the key. Two people typing the same thing want the same
    // cached answer, and clearing the box must not evict the previous result — the
    // omnibar re-opens onto what you last searched.
    results: (q: string, limit: number) => ["search", "results", q, limit] as const,
    // Config is per-caller and changes only when their role's permissions do, so it
    // is fetched once per session rather than per keystroke.
    config: ["search", "config"] as const,
  },

  schools: {
    all: ["schools"] as const,
    list: (params: SchoolListParams) => ["schools", "list", params] as const,
    detail: (id: string) => ["schools", "detail", id] as const,
    current: ["schools", "current"] as const,
  },
} as const;
