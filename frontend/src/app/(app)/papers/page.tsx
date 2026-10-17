import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { PapersView } from "./papers-view";

export const metadata: Metadata = { title: "Test papers" };
export const dynamic = "force-dynamic";

/**
 * Test papers written by the agent from the library's chapters. Like books, they
 * belong to one campus's classes; who may change WHICH paper is decided per paper by
 * the server and arrives as `can_edit`.
 */
export default async function PapersPage() {
  const { user } = await requireSchoolContext();
  if (!hasPermission(user, PERMISSIONS.paperRead)) redirect("/dashboard");

  return (
    <PapersView
      canWrite={
        hasPermission(user, PERMISSIONS.paperWrite) || hasPermission(user, PERMISSIONS.paperManage)
      }
    />
  );
}
