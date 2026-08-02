import type { Metadata } from "next";

import { ClassesView } from "./classes-view";
import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Classes" };
export const dynamic = "force-dynamic";

/**
 * Class and section structure for the active school.
 *
 * `canManage` is now a PERMISSION check, not a role-name comparison. The old
 * `user.role === "school_admin"` could not express the custom roles customers
 * create — a school that defines "Head of Curriculum" and expects them to manage
 * classes would have had to be given the full admin role instead, which is how
 * least-privilege quietly stops being practised.
 */
export default async function ClassesPage() {
  const user = await requireSchoolContext();
  return <ClassesView canManage={hasPermission(user, PERMISSIONS.classCreate)} />;
}
