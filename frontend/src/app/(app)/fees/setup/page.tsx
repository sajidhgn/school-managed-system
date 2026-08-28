import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { FeeSetupView } from "./fee-setup-view";
import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Fee heads & structures" };
export const dynamic = "force-dynamic";

/**
 * What the campus charges, before anybody is charged it.
 *
 * The whole page is one permission — `fee:manage` — so unlike the collection screen
 * there is nothing useful to show a reader who lacks it. Sending them back to the
 * register is better than an empty page they cannot act on.
 */
export default async function FeeSetupPage() {
  const { user } = await requireSchoolContext();
  if (!hasPermission(user, PERMISSIONS.feeManage)) redirect("/fees");

  // Configuring the schedule is `fee:manage`, which the redirect above already
  // settled. RUNNING it is `fee:issue` — deciding that this campus bills on the 25th
  // is a standing pricing decision, while pressing "run now" bills four hundred
  // families today, and the two are not the same trust.
  return <FeeSetupView canIssue={hasPermission(user, PERMISSIONS.feeIssue)} />;
}
