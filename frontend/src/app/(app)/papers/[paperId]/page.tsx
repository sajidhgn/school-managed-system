import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { PaperDetailView } from "./paper-detail-view";

export const metadata: Metadata = { title: "Test paper" };
export const dynamic = "force-dynamic";

/** One paper: its questions by section, the agent's report, and the review tools. */
export default async function PaperPage({ params }: { params: Promise<{ paperId: string }> }) {
  const { user } = await requireSchoolContext();
  if (!hasPermission(user, PERMISSIONS.paperRead)) redirect("/dashboard");
  const { paperId } = await params;
  return <PaperDetailView paperId={paperId} />;
}
