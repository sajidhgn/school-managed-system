import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { RolesView } from "./roles-view";
import { serverGetRequired } from "@/lib/api/server";
import { PERMISSIONS, type PermissionCategory, type RoleRead } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Roles" };

export default async function RolesPage() {
  const { user, schoolId } = await requireSchoolContext();

  // Hidden from the nav for anyone without the permission, but the URL still
  // resolves. Without this the API's 403 surfaced as a 500 page; a teacher who
  // types the address is sent home instead, as /fees and /schools already do.
  if (!hasPermission(user, PERMISSIONS.roleRead)) redirect("/dashboard");

  const [roles, catalog] = await Promise.all([
    serverGetRequired<RoleRead[]>(`/schools/${schoolId}/roles`),
    serverGetRequired<PermissionCategory[]>("/permissions"),
  ]);

  return (
    <RolesView
      schoolId={schoolId}
      roles={roles}
      catalog={catalog}
      // The actor's OWN permission set. The matrix greys out anything they do not
      // hold, because the server refuses to let anyone grant beyond their own
      // grant — see spec §5.3 rule 1.
      actorPermissions={user.permissions}
    />
  );
}
