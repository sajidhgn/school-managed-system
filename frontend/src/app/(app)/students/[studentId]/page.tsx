import type { Metadata } from "next";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { StudentDetailView } from "./student-detail-view";

export const metadata: Metadata = { title: "Student" };
export const dynamic = "force-dynamic";

export default async function StudentDetailPage({
  params,
}: {
  params: Promise<{ studentId: string }>;
}) {
  const { studentId } = await params;
  const user = await requireSchoolContext();

  return <StudentDetailView studentId={studentId} canManage={hasPermission(user, PERMISSIONS.studentUpdate)} />;
}
