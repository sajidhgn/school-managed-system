import { Suspense } from "react";
import type { Metadata } from "next";

import { StudentsView } from "./students-view";
import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Students" };
export const dynamic = "force-dynamic";

/**
 * The student directory for the active school.
 *
 * `requireSchoolContext()`: students belong to a campus, so the org-level principal
 * is asked which one they mean rather than shown every campus at once.
 */
export default async function StudentsPage() {
  const { user } = await requireSchoolContext();
  return (
    // `StudentsView` reads the filters out of the query string, and Next requires a
    // boundary around `useSearchParams` for that.
    <Suspense>
      <StudentsView
        canManage={hasPermission(user, PERMISSIONS.studentCreate)}
        // The fee filter is a list of which families are behind on payments, so the
        // server refuses it without `fee:read` (403 FEE_READ_REQUIRED). Hiding the
        // control here is the same rule stated twice on purpose: the server check is
        // the guarantee, this one stops a teacher being shown a filter that can only
        // fail. Same reasoning as the members table's disabled rows.
        canFilterByFees={hasPermission(user, PERMISSIONS.feeRead)}
      />
    </Suspense>
  );
}
