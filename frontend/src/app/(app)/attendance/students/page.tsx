import type { Metadata } from "next";

import { requireSchoolContext } from "@/lib/auth/session";
import { attendanceMessages } from "@/lib/i18n/modules/attendance";
import { getCatalog } from "@/lib/i18n/server";
import { StudentAttendanceView } from "./student-attendance-view";

export async function generateMetadata(): Promise<Metadata> {
  const m = await getCatalog(attendanceMessages);
  return { title: m.meta.students };
}

export const dynamic = "force-dynamic";

/**
 * Every child's attendance on one table: today, this month, last month, the year.
 *
 * `section_id` / `class_id` in the query string pre-filter it, which is how a row on
 * the class analytics page links straight to that section's children. The scope —
 * the whole campus for a principal, their own sections for a teacher — is the
 * server's decision; this page only renders what it is given.
 */
export default async function StudentAttendancePage({
  searchParams,
}: {
  searchParams: Promise<{ section_id?: string; class_id?: string }>;
}) {
  await requireSchoolContext();
  const params = await searchParams;
  return (
    <StudentAttendanceView
      initialSectionId={params.section_id ?? null}
      initialClassId={params.class_id ?? null}
    />
  );
}
