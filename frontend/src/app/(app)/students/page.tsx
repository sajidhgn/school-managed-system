import { Suspense } from "react";
import type { Metadata } from "next";

import { StudentsView } from "./students-view";
import { serverGet } from "@/lib/api/server";
import { PERMISSIONS, type OrganizationRead } from "@/lib/api/types";
import { hasPermission, listSchools, requireSchoolContext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Students" };
export const dynamic = "force-dynamic";

/**
 * The student directory for the active school.
 *
 * `requireSchoolContext()`: students belong to a campus, so the org-level principal
 * is asked which one they mean rather than shown every campus at once.
 */
export default async function StudentsPage() {
  const { user, schoolId } = await requireSchoolContext();

  // Names and brands the printable student card's header. `listSchools` returns []
  // when the caller can't read schools; the card then falls back to a generic
  // title rather than the page failing.
  const school = (await listSchools()).find((s) => s.id === schoolId) ?? null;

  // Branding resolves school-over-organization, field by field — but the colour
  // PALETTE inherits as a whole (a branch with its own palette never borrows the
  // trust's secondary; palettes are designed together). Callers without
  // `org:read` simply lose the inherited half — the card still renders with
  // whatever the branch set itself.
  const org = hasPermission(user, PERMISSIONS.orgRead)
    ? await serverGet<OrganizationRead | null>("/org", null)
    : null;

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
        // Same rule stated twice for the exam-result filter: the server refuses
        // `?exam=` without `grade:read` (403 GRADE_READ_REQUIRED); hiding the
        // control stops anyone being shown a filter that can only fail.
        canFilterByResults={hasPermission(user, PERMISSIONS.gradeRead)}
        // Whether this user may redesign and save the campus's card template —
        // the principal's job, so it rides on `school:update`, not on the
        // student permissions that gate the rest of this page.
        canDesignCard={hasPermission(user, PERMISSIONS.schoolUpdate)}
        school={
          school
            ? {
                id: school.id,
                name: school.name,
                code: school.code,
                phone: school.phone,
                // The card's BACK face is the administrative one: where the
                // school is and how to reach it when a card is found.
                email: school.email,
                address: school.address,
                city: school.city,
                logoUrl: school.logo_url ?? org?.logo_url ?? null,
                themeColors: school.theme_colors?.length
                  ? school.theme_colors
                  : (org?.theme_colors ?? null),
                cardDesign: school.card_design ?? null,
              }
            : null
        }
      />
    </Suspense>
  );
}
