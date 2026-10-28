import type { Metadata } from "next";
import { redirect } from "next/navigation";

import type { Branch } from "./add-member-form";
import { MembersView } from "./members-view";
import { serverGet, serverGetRequired } from "@/lib/api/server";
import {
  PERMISSIONS,
  type InvitationRead,
  type MemberRead,
  type Page,
  type RoleRead,
  type SchoolRead,
  type UsageResponse,
} from "@/lib/api/types";
import { hasPermission, requireUser } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Members" };

/**
 * Staff across every branch the caller can see, with invitations folded in as a
 * collapsible section.
 *
 * `requireUser()`, NOT `requireSchoolContext()`: Members does not depend on the
 * campus picker. The principal lands here straight after signing in and adds staff
 * to any branch from the Add member dialog. `?school=` narrows the list to one
 * branch — a filter, not a precondition. A school-scoped member is held to their
 * own branch by the server whatever the URL says.
 *
 * The filters — `?school=`, `?q=` (name or email) and `?role=` (a role code) — live
 * in the URL, so a filtered list survives Back and can be sent to a colleague.
 *
 * The invitation list has its own `?istatus=` and `?ipage=`, and follows `?school=`.
 *
 * `?invite=1` opens the invitation section on load — the deep link the old
 * standalone /invitations page redirects to.
 */
export default async function MembersPage({
  searchParams,
}: {
  searchParams: Promise<{
    invite?: string;
    page?: string;
    school?: string;
    q?: string;
    role?: string;
    istatus?: string;
    ipage?: string;
  }>;
}) {
  const [user, { invite, page, school, q, role, istatus, ipage }] = await Promise.all([
    requireUser(),
    searchParams,
  ]);

  // Hidden from the nav for anyone without the permission, but the URL still
  // resolves. Without this the API's 403 surfaced as a 500 page; a teacher who
  // types the address is sent home instead, as /fees and /schools already do.
  if (!hasPermission(user, PERMISSIONS.memberRead)) redirect("/dashboard");

  // The backend rejects page < 1, so a mangled or negative `?page=` falls back to 1
  // rather than turning a bookmarkable URL into a 422.
  const pageNumber = Math.max(1, Number.parseInt(page ?? "1", 10) || 1);

  // Read first: the filter and every per-branch read below are keyed on it. Optional,
  // because it needs `school:read` — the staff table must not hinge on it.
  const schools = await serverGet<SchoolRead[]>("/schools", []);
  const isOrgLevel = user.school_id === null;

  // The branches a member can be added to. A school-scoped administrator has exactly
  // one — their own — named from the session if `/schools` was closed to them.
  const branches: Branch[] = isOrgLevel
    ? schools.filter((s) => s.status === "active").map(({ id, name }) => ({ id, name }))
    : [
        {
          id: user.school_id as string,
          name:
            schools.find((s) => s.id === user.school_id)?.name ??
            user.school_name ??
            "Current school",
        },
      ];
  const branchNames: Record<string, string> = Object.fromEntries([
    ...schools.map((s) => [s.id, s.name]),
    ...branches.map((b) => [b.id, b.name]),
  ]);

  // Only an id the caller can actually see becomes a filter. Anything else — a stale
  // bookmark, a hand-edited URL — shows every branch rather than a 422 (the API
  // validates it as a UUID) or a silently empty table.
  const schoolFilter =
    isOrgLevel && school && Object.keys(branchNames).includes(school) ? school : null;
  // Shaped to what the API accepts (`q` 1–200 characters, `role` a role code), so an
  // edited URL narrows to nothing instead of failing the page with a 422. Not checked
  // against the role list: that would hold the staff read until the roles arrived.
  const search = (q ?? "").trim().slice(0, 200);
  const roleFilter = role && /^[a-z][a-z0-9_]{0,49}$/.test(role) ? role : null;

  const membersQuery = new URLSearchParams({ page: String(pageNumber), size: "20" });
  if (schoolFilter) membersQuery.set("school_id", schoolFilter);
  if (search) membersQuery.set("q", search);
  if (roleFilter) membersQuery.set("role", roleFilter);

  // Roles for every branch a row or the form may need. One request per branch, in
  // parallel — organizations run a handful, and role lists are short.
  const roleBranchIds = [...new Set([...branches.map((b) => b.id), ...(schoolFilter ? [schoolFilter] : [])])];

  // The invitation list's own filter and page, shaped like the API's so a hand-edited
  // URL shows everything rather than a 422.
  const invitationStatus =
    istatus && ["pending", "accepted", "expired", "revoked"].includes(istatus) ? istatus : null;
  const invitationPage = Math.max(1, Number.parseInt(ipage ?? "1", 10) || 1);
  const invitationScope = schoolFilter ? `&school_id=${schoolFilter}` : "";

  const [members, roleLists, invitations, pendingInvitations, usage] = await Promise.all([
    // The subject of the page. Without it there is nothing to render, so a failure
    // here should fail loudly rather than show an empty staff list that reads as
    // "this organization has no staff".
    serverGetRequired<Page<MemberRead>>(`/org/members?${membersQuery.toString()}`),
    // SUPPORTING data, and deliberately optional. Roles only populate the role pickers,
    // which are already gated on `member:invite` / `member:update`. Requiring them took
    // the whole page down with a 500 for anyone holding `member:read` but not
    // `role:read`.
    Promise.all(roleBranchIds.map((id) => serverGet<RoleRead[]>(`/schools/${id}/roles`, []))),
    // Also optional: the invitation section is gated on `invitation:read` /
    // `member:invite` in the view, but a member without those must still see the
    // staff table rather than a 500. Filtered and paged in the database.
    serverGet<Page<InvitationRead> | null>(
      `/org/invitations?page=${invitationPage}&size=10${invitationScope}${
        invitationStatus ? `&status=${invitationStatus}` : ""
      }`,
      null,
    ),
    // The pending badge: the database's count, one row fetched for its total.
    serverGet<Page<InvitationRead> | null>(
      `/org/invitations?status=pending&size=1${invitationScope}`,
      null,
    ),
    // Fetched so the Add member dialog can warn BEFORE the send that no staff seats
    // remain. The server enforces the limit (402 before anything is written); this
    // makes it visible rather than a surprise.
    serverGet<UsageResponse | null>("/org/usage", null),
  ]);

  // Only a branch's OWN roles are assignable there. Each list also carries the
  // org-level `principal` role, but that is transferred, never granted — the server
  // rejects it.
  const rolesByBranch: Record<string, RoleRead[]> = Object.fromEntries(
    roleBranchIds.map((id, i) => [id, (roleLists[i] ?? []).filter((r) => r.school_id === id)]),
  );
  // The role filter's choices, one per role CODE: every branch has its own "Teacher"
  // row, and the filter means all of them. The org-level principal role is included
  // here — it is a real role on the list, just not one the forms can grant.
  const roleOptions = [
    ...new Map(roleLists.flat().map((r) => [r.code, { code: r.code, name: r.name }])).values(),
  ].sort((a, b) => a.name.localeCompare(b.name));

  const emptyPage = { page: 1, size: 10, total: 0, pages: 0, has_next: false, has_prev: false };
  const staffSeats = usage?.items.find((i) => i.key === "max_staff") ?? null;

  return (
    <MembersView
      initialMembers={members.items}
      membersMeta={members.meta}
      invitations={invitations ?? { items: [], meta: emptyPage }}
      pendingInvitations={pendingInvitations?.meta.total ?? 0}
      invitationStatus={invitationStatus}
      rolesByBranch={rolesByBranch}
      branches={branches}
      branchNames={branchNames}
      schools={schools}
      filters={{ school: schoolFilter, q: search, role: roleFilter }}
      roleOptions={roleOptions}
      isOrgLevel={isOrgLevel}
      staffSeats={staffSeats}
      canAssignBranches={user.role_code === "principal"}
      currentMembershipId={user.active_membership_id}
      initialInviteOpen={invite === "1"}
    />
  );
}
