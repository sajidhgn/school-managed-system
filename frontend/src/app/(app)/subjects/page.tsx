import type { Metadata } from "next";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { SubjectsView } from "./subjects-view";

export const metadata: Metadata = { title: "Subjects" };
export const dynamic = "force-dynamic";

/**
 * The subject catalog and each class's curriculum.
 *
 * Gated on `subject:*`, which is granted read-only to the teacher role by default:
 * a teacher needs to see what their grade studies, and does not need to redefine
 * the school's curriculum to do it.
 */
export default async function SubjectsPage() {
  const { user } = await requireSchoolContext();
  return <SubjectsView canManage={hasPermission(user, PERMISSIONS.subjectManage)} />;
}
