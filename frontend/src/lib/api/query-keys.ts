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
  },

  schools: {
    all: ["schools"] as const,
    list: (params: SchoolListParams) => ["schools", "list", params] as const,
    detail: (id: string) => ["schools", "detail", id] as const,
    current: ["schools", "current"] as const,
  },
} as const;
