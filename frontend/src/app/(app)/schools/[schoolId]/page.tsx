import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { SchoolDetailView } from "./school-detail-view";
import { serverGet, serverGetOrNull } from "@/lib/api/server";
import {
  PERMISSIONS,
  type InvitationRead,
  type MemberRead,
  type Page,
  type RoleRead,
  type SchoolRead,
} from "@/lib/api/types";
import { getActiveSchoolId, hasPermission, requireUser } from "@/lib/auth/session";

export const metadata: Metadata = { title: "School" };

/**
 * One campus: its profile, and how much of the organization sits inside it.
 *
 * `requireUser()`, not `requireSchoolContext()` — deliberately. This page names the
 * campus in its own URL, so asking the reader to first *select* a campus in order to
 * look at a campus would be circular. The backend authorises from the path id
 * against the caller's scope, which is what makes reading School B legitimate while
 * School A is the active one.
 *
 * The counts degrade to empty rather than failing the page: a school-scoped member
 * who can see this campus but not its staff list still gets the profile, instead of
 * an error where a card would do.
 */
export default async function SchoolDetailPage({
  params,
}: {
  params: Promise<{ schoolId: string }>;
}) {
  const { schoolId } = await params;
  const user = await requireUser();

  const school = await serverGetOrNull<SchoolRead>(`/schools/${schoolId}`);
  // 404 rather than an empty shell: a school id that does not exist, or belongs to
  // another organization, must not render a page the reader could type into.
  if (!school) notFound();

  const [members, invitations, roles, activeSchoolId] = await Promise.all([
    // Only the count is shown; the smallest page carries it in its metadata.
    hasPermission(user, PERMISSIONS.memberRead)
      ? serverGet<Page<MemberRead> | null>(`/schools/${schoolId}/members?size=1`, null)
      : Promise.resolve<Page<MemberRead> | null>(null),
    hasPermission(user, PERMISSIONS.invitationRead)
      ? serverGet<InvitationRead[]>(`/schools/${schoolId}/invitations`, [])
      : Promise.resolve<InvitationRead[]>([]),
    hasPermission(user, PERMISSIONS.roleRead)
      ? serverGet<RoleRead[]>(`/schools/${schoolId}/roles`, [])
      : Promise.resolve<RoleRead[]>([]),
    getActiveSchoolId(),
  ]);

  return (
    <SchoolDetailView
      school={school}
      memberCount={members?.meta.total ?? 0}
      pendingInvitationCount={invitations.filter((i) => i.status === "pending").length}
      roleCount={roles.filter((r) => r.school_id === schoolId).length}
      // Org-level users pick which campus the school-scoped pages render. A
      // school-scoped member has no say in it, so they are never offered the choice.
      canSelectCampus={user.school_id === null}
      isActiveCampus={activeSchoolId === schoolId}
    />
  );
}
