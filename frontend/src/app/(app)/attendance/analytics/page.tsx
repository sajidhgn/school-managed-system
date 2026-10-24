import type { Metadata } from "next";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { AnalyticsView } from "./analytics-view";

export const metadata: Metadata = { title: "Attendance analytics" };
export const dynamic = "force-dynamic";

/**
 * Attendance class by class: which sections are slipping, whether registers are
 * being marked, and which children are falling below the threshold.
 *
 * `attendance:read` is enforced by the API; a caller without it gets the error
 * state's "You don't have access" rather than a page of zeroes. A teacher without
 * `class:view_all` sees the same screen over their own sections only — the bound is
 * applied on the server, not by hiding rows here.
 *
 * `calendar:read` only decides whether "This term" is offered: resolving a term to
 * dates needs the term list, and a role without it still gets the fixed ranges.
 */
export default async function AttendanceAnalyticsPage() {
  const { user } = await requireSchoolContext();
  return <AnalyticsView canReadCalendar={hasPermission(user, PERMISSIONS.calendarRead)} />;
}
