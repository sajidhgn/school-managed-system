import type { Metadata } from "next";

import { RolesView } from "./roles-view";
import { serverGetRequired } from "@/lib/api/server";
import type { PermissionCategory, RoleRead } from "@/lib/api/types";
import { requireSchoolContext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Roles" };

export default async function RolesPage() {
  const { user, schoolId } = await requireSchoolContext();

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
