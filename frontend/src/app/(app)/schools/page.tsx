import type { Metadata } from "next";

import { SchoolsView } from "./schools-view";
import { serverGetRequired } from "@/lib/api/server";
import type { SchoolRead, UsageResponse } from "@/lib/api/types";
import { requireUser } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Schools" };

/**
 * The organization's campuses.
 *
 * `requireUser()`, not `requireSchoolContext()`: this is one of the few pages that
 * is MORE useful at org level. The principal sees every school; a school-scoped member
 * sees only their own, because the server's list endpoint applies the same scope
 * their token carries.
 */
export default async function SchoolsPage() {
  const user = await requireUser();

  const [schools, usage] = await Promise.all([
    serverGetRequired<SchoolRead[]>("/schools"),
    serverGetRequired<UsageResponse>("/org/usage"),
  ]);

  const schoolSeats = usage?.items.find((i) => i.key === "max_schools") ?? null;

  return (
    <SchoolsView
      schools={schools}
      schoolSeats={schoolSeats}
      // Opening a card moves the sidebar's campus modules to that branch. Only an
      // org-level user has a branch to move to; a school-scoped member is already
      // in theirs and stays there.
      canSelectCampus={user.school_id === null}
    />
  );
}
