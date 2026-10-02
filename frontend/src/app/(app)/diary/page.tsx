import type { Metadata } from "next";

import { serverGet } from "@/lib/api/server";
import { PERMISSIONS, type OrganizationRead } from "@/lib/api/types";
import { hasPermission, listSchools, requireSchoolContext } from "@/lib/auth/session";
import { DiaryView } from "./diary-view";

export const metadata: Metadata = { title: "Diary" };
export const dynamic = "force-dynamic";

/**
 * The daily class diary for the active school.
 *
 * Who may write WHICH row is decided by the server per row (class teacher: every
 * subject; subject teacher: their own) and arrives as `can_edit`. The permission
 * checks here only decide whether the page offers editing at all.
 */
export default async function DiaryPage() {
  const { user, schoolId } = await requireSchoolContext();

  // Branding for the shareable diary image, resolved school-over-organization the
  // same way the student card does. Missing reads degrade to a plain header.
  const school = (await listSchools()).find((s) => s.id === schoolId) ?? null;
  const org = hasPermission(user, PERMISSIONS.orgRead)
    ? await serverGet<OrganizationRead | null>("/org", null)
    : null;
  const colors = school?.theme_colors?.length ? school.theme_colors : (org?.theme_colors ?? null);

  return (
    <DiaryView
      canWrite={
        hasPermission(user, PERMISSIONS.diaryWrite) || hasPermission(user, PERMISSIONS.diaryManage)
      }
      branding={{
        schoolName: school?.name ?? org?.name ?? "Class Diary",
        subtitle: school?.city ?? null,
        logoUrl: school?.logo_url ?? org?.logo_url ?? null,
        primaryColor: colors?.[0] ?? null,
      }}
    />
  );
}
