import type { Metadata } from "next";

import { requireUser } from "@/lib/auth/session";
import { StudentDetailView } from "./student-detail-view";

export const metadata: Metadata = { title: "Student" };
export const dynamic = "force-dynamic";

export default async function StudentDetailPage({
  params,
}: {
  params: Promise<{ studentId: string }>;
}) {
  const { studentId } = await params;
  const user = await requireUser();

  return <StudentDetailView studentId={studentId} canManage={user.role === "school_admin"} />;
}
