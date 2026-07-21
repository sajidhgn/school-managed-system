import type { Metadata } from "next";

import { requireUser } from "@/lib/auth/session";
import { ClassesView } from "./classes-view";

export const metadata: Metadata = { title: "Classes" };
export const dynamic = "force-dynamic";

export default async function ClassesPage() {
  const user = await requireUser();
  // Teachers need the structure to navigate the school, but only admins may
  // reshape it; the backend enforces the same with require_roles("school_admin").
  return <ClassesView canManage={user.role === "school_admin"} />;
}
