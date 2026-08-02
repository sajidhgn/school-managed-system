import type { Metadata } from "next";

import { StudentsView } from "./students-view";
import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Students" };
export const dynamic = "force-dynamic";

/**
 * The student directory for the active school.
 *
 * `requireSchoolContext()`: students belong to a campus, so an org-level owner is
 * asked which one they mean rather than shown an empty roster.
 */
export default async function StudentsPage() {
  const user = await requireSchoolContext();
  return <StudentsView canManage={hasPermission(user, PERMISSIONS.studentCreate)} />;
}
