import type { Metadata } from "next";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { ExamsView } from "./exams-view";

export const metadata: Metadata = { title: "Exams" };
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
  return <ExamsView canManage={hasPermission(user, PERMISSIONS.gradeManage)} />;
}
