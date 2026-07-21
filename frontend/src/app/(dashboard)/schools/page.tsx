import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { requireUser } from "@/lib/auth/session";
import { SchoolsView } from "./schools-view";

export const metadata: Metadata = { title: "Schools" };
export const dynamic = "force-dynamic";

export default async function SchoolsPage() {
  const user = await requireUser();
  // Every tenancy route except /schools/current is require_super_admin on the
  // backend; redirecting here avoids rendering a page that could only ever 403.
  if (user.role !== "super_admin") redirect("/dashboard");
  return <SchoolsView />;
}
