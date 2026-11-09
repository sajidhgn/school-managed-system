import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { AdmissionsView } from "./admissions-view";
import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { studentsMessages } from "@/lib/i18n/modules/students";
import { getCatalog } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getCatalog(studentsMessages)).meta.admissions };
}
export const dynamic = "force-dynamic";

/**
 * The admissions queue: applications sent through the public form, waiting for a
 * decision.
 *
 * A campus page, like the directory: an application is made to one school, and the
 * public form link it shares is that school's.
 */
export default async function AdmissionsPage() {
  const { user, schoolId } = await requireSchoolContext();
  if (!hasPermission(user, PERMISSIONS.studentRead)) redirect("/dashboard");

  return (
    <AdmissionsView
      schoolId={schoolId}
      // Admitting changes the status (and takes a plan seat): `student:update`.
      canAdmit={hasPermission(user, PERMISSIONS.studentUpdate)}
      // Declining removes the applicant from the directory: `student:delete`.
      canDecline={hasPermission(user, PERMISSIONS.studentDelete)}
    />
  );
}
