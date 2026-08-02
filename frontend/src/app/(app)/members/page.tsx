import type { Metadata } from "next";

import { MembersView } from "./members-view";
import { serverGet } from "@/lib/api/server";
import type { MemberRead, RoleRead } from "@/lib/api/types";
import { requireSchoolContext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Members" };

/**
 * Staff of the active school.
 *
 * `requireSchoolContext()` rather than `requireUser()`: membership is school-scoped,
 * so an org-level owner is asked which campus they mean instead of being shown an
 * empty list or an error.
 */
export default async function MembersPage() {
  const user = await requireSchoolContext();
  const schoolId = user.school_id!;

  const [members, roles] = await Promise.all([
    serverGet<MemberRead[]>(`/schools/${schoolId}/members`, []),
    serverGet<RoleRead[]>(`/schools/${schoolId}/roles`, []),
  ]);

  return (
    <MembersView
      schoolId={schoolId}
      initialMembers={members}
      roles={roles}
      currentMembershipId={user.active_membership_id}
    />
  );
}
