import type { Metadata } from "next";

import { requireUser } from "@/lib/auth/session";
import { DashboardView } from "./dashboard-view";

export const metadata: Metadata = { title: "Dashboard" };
export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const user = await requireUser();
  return <DashboardView user={user} />;
}
