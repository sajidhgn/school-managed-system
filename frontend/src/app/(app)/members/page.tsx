import type { Metadata } from "next";

import { MembersView } from "./members-view";
import { serverGet, serverGetRequired } from "@/lib/api/server";
import type {
  InvitationRead,
  MemberRead,
  Page,
  RoleRead,
  SchoolRead,
  UsageResponse,
} from "@/lib/api/types";
import { requireSchoolContext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Members" };

/**
 * Staff of the active school, with invitations folded in as a collapsible section.
 *
 * `requireSchoolContext()` rather than `requireUser()`: membership is school-scoped,
 * so the org-level principal is asked which campus they mean instead of being shown
 * an empty list or an error.
 *
 * `?invite=1` opens the invitation section on load — the deep link the old
 * standalone /invitations page redirects to.
 */
export default async function MembersPage({
  searchParams,
}: {
  searchParams: Promise<{ invite?: string; page?: string }>;
}) {
  const [{ user, schoolId }, { invite, page }] = await Promise.all([
    requireSchoolContext(),
    searchParams,
  ]);

  // The backend rejects page < 1, so a mangled or negative `?page=` falls back to 1
  // rather than turning a bookmarkable URL into a 422.
  const pageNumber = Math.max(1, Number.parseInt(page ?? "1", 10) || 1);

  const [members, roles, schools, invitations, usage] = await Promise.all([
    // The subject of the page. Without it there is nothing to render, so a failure
    // here should fail loudly rather than show an empty staff list that reads as
    // "this school has no staff".
    serverGetRequired<Page<MemberRead>>(
      `/schools/${schoolId}/members?page=${pageNumber}&size=20`,
    ),
    // SUPPORTING data, and deliberately optional. Roles only populate the "change
    // role to" menu, which is already gated on `member:update`. Requiring them took
    // the whole page down with a 500 for anyone holding `member:read` but not
    // `role:read` — a plain teacher, whose sidebar offers them this very link.
    serverGet<RoleRead[]>(`/schools/${schoolId}/roles`, []),
    serverGet<SchoolRead[]>("/schools", []),
    // Also optional: the invitation section is gated on `invitation:read` /
    // `member:invite` in the view, but a member without those must still see the
    // staff table rather than a 500.
    serverGet<InvitationRead[]>(`/schools/${schoolId}/invitations`, []),
    // Fetched so the invite form can warn BEFORE the send that no staff seats
    // remain. The server enforces the limit (402 before the email goes out); this
    // makes it visible rather than a surprise.
    serverGet<UsageResponse | null>("/org/usage", null),
  ]);

  const staffSeats = usage?.items.find((i) => i.key === "max_staff") ?? null;
  const schoolName =
    schools.find((s) => s.id === schoolId)?.name ?? user.school_name ?? "Current school";

  return (
    <MembersView
      schoolId={schoolId}
      schoolName={schoolName}
      initialMembers={members.items}
      membersMeta={members.meta}
      invitations={invitations}
      roles={roles}
      schools={schools}
      staffSeats={staffSeats}
      canAssignBranches={user.role_code === "principal"}
      currentMembershipId={user.active_membership_id}
      initialInviteOpen={invite === "1"}
    />
  );
}
