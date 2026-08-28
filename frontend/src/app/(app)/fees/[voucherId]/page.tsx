import type { Metadata } from "next";

import { VoucherDetailView } from "./voucher-detail-view";
import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Challan" };
export const dynamic = "force-dynamic";

export default async function VoucherPage({
  params,
}: {
  params: Promise<{ voucherId: string }>;
}) {
  const { voucherId } = await params;
  const { user } = await requireSchoolContext();

  return (
    <VoucherDetailView
      voucherId={voucherId}
      canIssue={hasPermission(user, PERMISSIONS.feeIssue)}
      canCollect={hasPermission(user, PERMISSIONS.feeCollect)}
      // Voiding and reversing are one permission, held by the principal and not by
      // the accountant default — whoever takes the money must not be able to erase
      // the record of it.
      canVoid={hasPermission(user, PERMISSIONS.feeVoid)}
    />
  );
}
