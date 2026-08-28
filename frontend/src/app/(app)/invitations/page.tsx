import type { Metadata } from "next";

import { InvitationsView } from "./invitations-view";
import { serverGet, serverGetRequired } from "@/lib/api/server";
import type { InvitationRead, RoleRead, SchoolRead, UsageResponse } from "@/lib/api/types";
import { requireSchoolContext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Invitations" };

export default async function InvitationsPage() {
  const { user, schoolId } = await requireSchoolContext();

  const [invitations, roles, school, usage] = await Promise.all([
    // The subject of the page; an empty list here means something different from a
    // failed read, so this one stays required.
    serverGetRequired<InvitationRead[]>(`/schools/${schoolId}/invitations`),
    // Supporting data. The invite form needs roles, but somebody who may read
    // invitations without holding `role:read` should still see the list rather than
    // a 500 — the form is gated on `member:invite` separately.
    serverGet<RoleRead[]>(`/schools/${schoolId}/roles`, []),
    // The session only names the school for a school-scoped member. The principal's
    // campus comes from their selection, so the name is read from the school itself.
    serverGet<SchoolRead | null>(`/schools/${schoolId}`, null),
    // Fetched so the form can warn BEFORE the send that no staff seats remain.
    // The server enforces the limit (402 before the email goes out); this makes it
    // visible rather than a surprise.
    serverGet<UsageResponse | null>("/org/usage", null),
  ]);

  const staffSeats = usage?.items.find((i) => i.key === "max_staff") ?? null;

  return (
    <InvitationsView
      schoolId={schoolId}
      schoolName={school?.name ?? user.school_name ?? "Current school"}
      invitations={invitations}
      roles={roles.filter((r) => r.school_id === schoolId)}
      staffSeats={staffSeats}
    />
  );
}
