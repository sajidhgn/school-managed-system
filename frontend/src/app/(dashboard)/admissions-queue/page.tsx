import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { requireUser } from "@/lib/auth/session";
import { AdmissionsQueueView } from "./admissions-queue-view";

export const metadata: Metadata = { title: "Admissions" };
export const dynamic = "force-dynamic";

export default async function AdmissionsQueuePage() {
  const user = await requireUser();
  // Teachers can read the roster but admitting a student is an administrative
  // decision; the backend enforces the same rule on the PATCH route.
  if (user.role !== "school_admin") redirect("/dashboard");

  return <AdmissionsQueueView />;
}
