import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { ContextPicker } from "@/components/auth/context-picker";
import { SchoolPicker } from "@/components/auth/school-picker";
import { serverGet } from "@/lib/api/server";
import type { SchoolRead } from "@/lib/api/types";
import { getActiveSchoolId, requireUser } from "@/lib/auth/session";
import { getTranslations } from "@/lib/i18n/server";

export const metadata: Metadata = { title: "Choose a school" };

/**
 * Where `requireSchoolContext()` sends a user with no active campus.
 *
 * The principal is org-level (`school_id` is null), which is right for billing, the
 * school list and organization settings — but meaningless for members, roles,
 * invitations or attendance. Rather than erroring on those pages, they are asked
 * which campus they mean.
 *
 * =============================================================================
 * PICKING A CAMPUS IS NOT SWITCHING CONTEXT
 * =============================================================================
 *   The principal holds ONE membership, and it spans every school. So this page
 *   lists the organization's SCHOOLS and records the choice as a view preference.
 *   Their authority is identical before and after.
 *
 *   Someone who holds school-scoped memberships instead — a teacher at two campuses,
 *   or at two different organizations — gets the membership picker, because for them
 *   the campus IS the authorisation scope and moving between campuses genuinely
 *   re-issues the session.
 *
 * An organization with no schools yet goes to onboarding either way: offering a
 * picker with nothing in it is a dead end.
 */
export default async function SelectSchoolPage() {
  const [user, t] = await Promise.all([requireUser(), getTranslations()]);

  if (user.school_id) redirect("/dashboard");

  const schoolMemberships = user.memberships.filter((m) => !m.is_org_level);
  const schools = schoolMemberships.length > 0 ? [] : await serverGet<SchoolRead[]>("/schools", []);
  const activeSchoolId = await getActiveSchoolId();

  if (schoolMemberships.length === 0 && schools.length === 0) redirect("/onboarding");

  return (
    <div className="mx-auto w-full max-w-md py-10">
      <h1 className="text-2xl font-semibold tracking-tight">{t.selectSchool.title}</h1>
      <p className="mt-2 text-muted-foreground text-pretty">{t.selectSchool.body}</p>
      <div className="mt-8 rounded-xl border border-border bg-card p-6">
        {schoolMemberships.length > 0 ? (
          <ContextPicker memberships={schoolMemberships} redirectTo="/dashboard" />
        ) : (
          <SchoolPicker schools={schools} activeSchoolId={activeSchoolId} redirectTo="/dashboard" />
        )}
      </div>
      <p className="mt-4 text-center text-xs text-muted-foreground">{t.auth.selectContextHint}</p>
    </div>
  );
}
