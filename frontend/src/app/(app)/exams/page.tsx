import type { Metadata } from "next";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { examsMessages } from "@/lib/i18n/modules/exams";
import { getCatalog } from "@/lib/i18n/server";
import { ExamsView } from "./exams-view";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getCatalog(examsMessages)).meta.list };
}

export const dynamic = "force-dynamic";

/**
 * The exam schedule and gradebook entry point.
 *
 * Gated on `grade:*`, which the teacher role holds in full by default: entering
 * marks is the teacher's job, while creating the exam itself usually is too --
 * a school that wants marks-entry-only teachers builds a custom role without
 * `grade:manage`.
 */
export default async function ExamsPage() {
  const { user } = await requireSchoolContext();
  return (
    <ExamsView
      canManage={hasPermission(user, PERMISSIONS.gradeManage)}
      // The grading scale is campus policy: marking rights alone do not change it.
      canSetGrading={hasPermission(user, PERMISSIONS.gradeManage, PERMISSIONS.schoolUpdate)}
    />
  );
}
