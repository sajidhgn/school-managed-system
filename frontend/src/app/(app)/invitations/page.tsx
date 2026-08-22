import type { Metadata } from "next";

import { InvitationsView } from "./invitations-view";
import { serverGetRequired } from "@/lib/api/server";
import type { InvitationRead, RoleRead, UsageResponse } from "@/lib/api/types";
import { requireSchoolContext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Invitations" };

export default async function InvitationsPage() {
  const user = await requireSchoolContext();
  const schoolId = user.school_id!;

  const [invitations, roles, usage] = await Promise.all([
    serverGetRequired<InvitationRead[]>(`/schools/${schoolId}/invitations`),
    serverGetRequired<RoleRead[]>(`/schools/${schoolId}/roles`),
    // Fetched so the form can warn BEFORE the send that no staff seats remain.
    // The server enforces the limit (402 before the email goes out); this makes it
    // visible rather than a surprise.
    serverGetRequired<UsageResponse>("/org/usage"),
  ]);

  const staffSeats = usage?.items.find((i) => i.key === "max_staff") ?? null;

  return (
    <InvitationsView
      schoolId={schoolId}
      invitations={invitations}
      roles={roles.filter((r) => r.school_id === schoolId)}
      staffSeats={staffSeats}
    />
  );
}
