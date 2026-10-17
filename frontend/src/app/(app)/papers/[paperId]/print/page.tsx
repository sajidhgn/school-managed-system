import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { serverGetOrNull } from "@/lib/api/server";
import { PERMISSIONS, type SchoolRead } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { PaperPrintView } from "./paper-print-view";

export const metadata: Metadata = { title: "Print test paper" };
export const dynamic = "force-dynamic";

/**
 * The paper as it goes to the printer. There is no server PDF: the teacher prints
 * this page, or saves it as a PDF from the browser's print dialog. The campus name
 * heads the paper, so it is read here with the session (null if it can't be).
 */
export default async function PaperPrintPage({ params }: { params: Promise<{ paperId: string }> }) {
  const { user, schoolId } = await requireSchoolContext();
  if (!hasPermission(user, PERMISSIONS.paperRead)) redirect("/dashboard");
  const { paperId } = await params;
  const school = await serverGetOrNull<SchoolRead>(`/schools/${schoolId}`);
  return <PaperPrintView paperId={paperId} schoolName={school?.name ?? user.school_name ?? null} />;
}
