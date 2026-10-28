import type { StructureListParams, VoucherListParams } from "@/lib/api/resources/fees";
import type {
  AnalyticsParams,
  SessionListParams,
  StudentAttendanceParams,
} from "@/lib/api/resources/attendance";
import type { ExamListParams } from "@/lib/api/resources/exams";
import type { BookListParams, LibraryParams } from "@/lib/api/resources/books";
import type { PaperListParams, QuestionBankParams } from "@/lib/api/resources/papers";
import type { SubjectListParams } from "@/lib/api/resources/subjects";
import type { StudentListParams } from "@/lib/api/resources/students";
import type { SchoolListParams } from "@/lib/api/resources/schools";
import type { DiaryAgentSettingsWrite, PageParams } from "@/lib/api/types";

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

  guardians: {
    /** The contact card on a student's page: who may sign in to the portal for them. */
    forStudent: (studentId: string) => ["guardians", "student", studentId] as const,
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

  books: {
    all: ["books"] as const,
    list: (params: BookListParams) => ["books", "list", params] as const,
    detail: (id: string) => ["books", "detail", id] as const,
    library: (params: LibraryParams) => ["books", "library", params] as const,
    librarySubjects: (grade: string) => ["books", "library-subjects", grade] as const,
    // `version` is the chapter's `processed_at`: a run finishing in the background
    // gives the pages a new key, so an open page list refetches by itself.
    pages: (bookId: string, chapterId: string, version: string | null) =>
      ["books", bookId, "pages", chapterId, version] as const,
    // Not under `detail`: polling the book while a chapter is processed must not
    // refetch every search the teacher already ran.
    search: (bookId: string, q: string) => ["books-search", bookId, q] as const,
    // Not under `all`: adding a book must not re-check the AI provider.
    scanStatus: ["books-scan-status"] as const,
  },

  papers: {
    all: ["papers"] as const,
    list: (params: PaperListParams) => ["papers", "list", params] as const,
    detail: (id: string) => ["papers", "detail", id] as const,
    // Under `papers.all`: editing a question on a paper edits it in the bank too.
    bank: (params: QuestionBankParams) => ["papers", "bank", params] as const,
  },

  whatsapp: {
    all: ["whatsapp"] as const,
    groups: ["whatsapp", "groups"] as const,
    settings: ["whatsapp", "settings"] as const,
    preview: (period: string) => ["whatsapp", "preview", period] as const,
    messages: (params: PageParams & { status?: string }) =>
      ["whatsapp", "messages", params] as const,
    // Polled while the number is being linked; under `whatsapp.all` so saving a group
    // refreshes the "N groups not reachable" count too.
    connection: ["whatsapp", "connection"] as const,
    qr: ["whatsapp", "connection", "qr"] as const,
    diarySettings: ["whatsapp", "diary-agent", "settings"] as const,
    // Keyed by the unsaved form values, so typing back to an earlier format is a cache hit.
    diaryPreview: (body: DiaryAgentSettingsWrite) =>
      ["whatsapp", "diary-agent", "preview", body] as const,
    diaryDrafts: (params: PageParams) => ["whatsapp", "diary-agent", "drafts", params] as const,
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
    analytics: (params: AnalyticsParams) => ["attendance", "analytics", params] as const,
    students: (params: StudentAttendanceParams) => ["attendance", "students", params] as const,
    calendar: (studentId: string, from: string | null, to: string | null) =>
      ["attendance", "calendar", studentId, from, to] as const,
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
