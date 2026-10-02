import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { FeesView } from "./fees-view";
import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, listSchools, requireSchoolContext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Fees" };
export const dynamic = "force-dynamic";

/**
 * Fee collection for the active campus.
 *
 * `requireSchoolContext()`: a challan belongs to one campus, and every figure on this
 * page is scoped to it. An org-level principal is asked which branch they mean rather
 * than shown five campuses' money added together, which would be a number nobody can
 * act on.
 *
 * The capability flags are resolved here and passed down rather than checked in the
 * view, so the whole page agrees about what this person may do. Hiding a control is
 * cosmetic — `require(...)` on each route is the actual gate.
 */
export default async function FeesPage() {
  const { user, schoolId } = await requireSchoolContext();

  // Without `fee:read` every panel on this page is a 403. Sending them back is
  // kinder than a shell full of "you don't have access to this" — the sidebar
  // already hides the link, so arriving here means a typed URL or a stale bookmark.
  if (!hasPermission(user, PERMISSIONS.feeRead)) redirect("/dashboard");

  // Carries the campus's printed-challan template. `listSchools` returns [] when the
  // caller cannot read schools; the designer is then simply unavailable and every
  // challan prints with the standard layout.
  const school = (await listSchools()).find((s) => s.id === schoolId) ?? null;

  return (
    <FeesView
      canIssue={hasPermission(user, PERMISSIONS.feeIssue)}
      canCollect={hasPermission(user, PERMISSIONS.feeCollect)}
      canManage={hasPermission(user, PERMISSIONS.feeManage)}
      // Redesigning the challan is the office's decision for the whole campus, and
      // it carries the bank accounts money is sent to — so it rides on
      // `school:update`, not on the fee permissions that gate the rest of the page.
      canDesignChallan={hasPermission(user, PERMISSIONS.schoolUpdate)}
      school={
        school
          ? {
              id: school.id,
              name: school.name,
              challanDesign: school.challan_design ?? null,
            }
          : null
      }
    />
  );
}
