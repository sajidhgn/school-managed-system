import type { Metadata } from "next";

import { SettingsView } from "./settings-view";
import { serverGet, serverGetRequired } from "@/lib/api/server";
import {
  PERMISSIONS,
  type MemberRead,
  type OrganizationRead,
  type SchoolRead,
} from "@/lib/api/types";
import { hasPermission, requireUser } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage() {
  const user = await requireUser();

  const canEditOrg = hasPermission(user, PERMISSIONS.orgUpdate);
  const organization = hasPermission(user, PERMISSIONS.orgRead)
    ? canEditOrg
      ? await serverGetRequired<OrganizationRead>("/org")
      : await serverGet<OrganizationRead | null>("/org", null)
    : null;
  const canTransferOwnership = hasPermission(user, PERMISSIONS.orgTransferOwnership);
  let ownershipCandidates: MemberRead[] = [];
  if (canTransferOwnership) {
    const schools = await serverGetRequired<SchoolRead[]>("/schools");
    const members = (
      await Promise.all(
        schools.map((school) =>
          serverGetRequired<MemberRead[]>(`/schools/${school.id}/members`),
        ),
      )
    ).flat();
    ownershipCandidates = [
      ...new Map(
        members
          .filter((member) => member.status === "active" && member.user_id !== user.user_id)
          .map((member) => [member.user_id, member]),
      ).values(),
    ];
  }

  return (
    <SettingsView
      user={user}
      organization={organization}
      canEditOrg={canEditOrg}
      canTransferOwnership={canTransferOwnership}
      ownershipCandidates={ownershipCandidates}
    />
  );
}
