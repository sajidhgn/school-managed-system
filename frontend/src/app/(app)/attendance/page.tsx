import type { Metadata } from "next";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { AttendanceView } from "./attendance-view";

export const metadata: Metadata = { title: "Attendance" };
export const dynamic = "force-dynamic";

/**
 * The daily register board for the active school.
 *
 * Both capabilities are PERMISSION checks, never role-name comparisons, and they
 * are two separate checks rather than one:
 *
 *   `attendance:mark`  open a register, mark it, submit it — the teacher's job.
 *   `attendance:amend` change or reopen one that was already submitted.
 *
 * A system where whoever records absences can also erase them has no attendance
 * record, only an attendance opinion. The UI has to reflect that split or it
 * quietly re-merges the two in the only place users can see.
 */
export default async function AttendancePage() {
  const { user } = await requireSchoolContext();
  return (
    <AttendanceView
      canMark={hasPermission(user, PERMISSIONS.attendanceMark)}
      canAmend={hasPermission(user, PERMISSIONS.attendanceAmend)}
    />
  );
}
