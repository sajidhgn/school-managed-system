import type { Metadata } from "next";

import { SettingsView } from "./settings-view";
import { serverGet } from "@/lib/api/server";
import { PERMISSIONS, type OrganizationRead } from "@/lib/api/types";
import { hasPermission, requireUser } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage() {
  const user = await requireUser();

  const organization = hasPermission(user, PERMISSIONS.orgRead)
    ? await serverGet<OrganizationRead | null>("/org", null)
    : null;

  return (
    <SettingsView
      user={user}
      organization={organization}
      canEditOrg={hasPermission(user, PERMISSIONS.orgUpdate)}
    />
  );
}
