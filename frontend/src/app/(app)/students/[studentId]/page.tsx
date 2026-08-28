import type { Metadata } from "next";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { StudentDetailView } from "./student-detail-view";

export const metadata: Metadata = { title: "Student" };
export const dynamic = "force-dynamic";

/**
 * The student's whole record — profile, placement and fee ledger on one page.
 *
 * Permissions are resolved HERE, from the session, and handed down as booleans. The
 * fee codes are separate from the student ones on purpose: a class teacher holds
 * `student:read` and no `fee:read`, so they get the record without the money, while
 * an accountant gets the money without the ability to edit the record.
 */
export default async function StudentDetailPage({
  params,
}: {
  params: Promise<{ studentId: string }>;
}) {
  const { studentId } = await params;
  const { user } = await requireSchoolContext();

  return (
    <StudentDetailView
      studentId={studentId}
      canManage={hasPermission(user, PERMISSIONS.studentUpdate)}
      canReadFees={hasPermission(user, PERMISSIONS.feeRead)}
      // Changing what a student is charged is a PRICING decision that recurs every
      // period, so it sits with `fee:manage` alongside structures — not with
      // `fee:issue`, which only runs what has already been decided.
      canManageFees={hasPermission(user, PERMISSIONS.feeManage)}
      canIssue={hasPermission(user, PERMISSIONS.feeIssue)}
      canCollect={hasPermission(user, PERMISSIONS.feeCollect)}
      // Voiding and reversing are one permission, held by the principal and not by
      // the accountant default — whoever takes the money must not be able to erase
      // the record of it.
      canVoid={hasPermission(user, PERMISSIONS.feeVoid)}
    />
  );
}
