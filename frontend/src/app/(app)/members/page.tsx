import type { Metadata } from "next";

import { MembersView } from "./members-view";
import { serverGet, serverGetRequired } from "@/lib/api/server";
import type { MemberRead, RoleRead, SchoolRead } from "@/lib/api/types";
import { requireSchoolContext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Members" };

/**
 * Staff of the active school.
 *
 * `requireSchoolContext()` rather than `requireUser()`: membership is school-scoped,
 * so the org-level principal is asked which campus they mean instead of being shown
 * an empty list or an error.
 */
export default async function MembersPage() {
  const { user, schoolId } = await requireSchoolContext();

  const [members, roles, schools] = await Promise.all([
    // The subject of the page. Without it there is nothing to render, so a failure
    // here should fail loudly rather than show an empty staff list that reads as
    // "this school has no staff".
    serverGetRequired<MemberRead[]>(`/schools/${schoolId}/members`),
    // SUPPORTING data, and deliberately optional. Roles only populate the "change
    // role to" menu, which is already gated on `member:update`. Requiring them took
    // the whole page down with a 500 for anyone holding `member:read` but not
    // `role:read` — a plain teacher, whose sidebar offers them this very link.
    serverGet<RoleRead[]>(`/schools/${schoolId}/roles`, []),
    serverGet<SchoolRead[]>("/schools", []),
  ]);

  return (
    <MembersView
      schoolId={schoolId}
      initialMembers={members}
      roles={roles}
      schools={schools}
      canAssignBranches={user.role_code === "principal"}
      currentMembershipId={user.active_membership_id}
    />
  );
}
