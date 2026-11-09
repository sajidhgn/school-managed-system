import type { Metadata } from "next";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { examsMessages } from "@/lib/i18n/modules/exams";
import { getCatalog } from "@/lib/i18n/server";
import { ExamDetailView } from "./exam-detail-view";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getCatalog(examsMessages)).meta.detail };
}

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
