import type { Metadata } from "next";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { ExamDetailView } from "./exam-detail-view";

export const metadata: Metadata = { title: "Exam" };
export const dynamic = "force-dynamic";

/** One exam: its papers, their mark sheets, and the class result sheets. */
export default async function ExamDetailPage({
  params,
}: {
  params: Promise<{ examId: string }>;
}) {
  const { user } = await requireSchoolContext();
  const { examId } = await params;
  return (
    <ExamDetailView
      examId={examId}
      canManage={hasPermission(user, PERMISSIONS.gradeManage)}
    />
  );
}
