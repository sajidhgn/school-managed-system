import type { Metadata } from "next";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { CalendarView } from "./calendar-view";

export const metadata: Metadata = { title: "Academic year" };
export const dynamic = "force-dynamic";

/**
 * The academic calendar: years and the terms inside them.
 *
 * `canBackfill` is checked against `student:promote`, NOT `calendar:manage`. The
 * backfill writes an enrollment row per student — the same bulk, whole-school blast
 * radius promotion has — so it is gated on the permission that describes that risk
 * rather than on the one that happens to own the screen it appears on.
 */
export default async function AcademicYearsPage() {
  const { user } = await requireSchoolContext();
  return (
    <CalendarView
      canManage={hasPermission(user, PERMISSIONS.calendarManage)}
      canBackfill={hasPermission(user, PERMISSIONS.studentPromote)}
    />
  );
}
