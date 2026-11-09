import type { Metadata } from "next";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { calendarMessages } from "@/lib/i18n/modules/calendar";
import { getCatalog } from "@/lib/i18n/server";
import { CalendarView } from "./calendar-view";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getCatalog(calendarMessages)).meta.title };
}

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
