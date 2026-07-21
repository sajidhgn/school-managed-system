import type { Metadata } from "next";

import { requireUser } from "@/lib/auth/session";
import { StudentsView } from "./students-view";

export const metadata: Metadata = { title: "Students" };
export const dynamic = "force-dynamic";

export default async function StudentsPage() {
  const user = await requireUser();
  // Teachers can read the roster but not mutate it; the backend enforces this
  // with require_roles("school_admin") on every write route.
  return <StudentsView canManage={user.role === "school_admin"} />;
}
