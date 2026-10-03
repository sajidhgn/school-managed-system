import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { WhatsAppView } from "./whatsapp-view";

export const metadata: Metadata = { title: "WhatsApp" };
export const dynamic = "force-dynamic";

/**
 * Class WhatsApp groups for the active campus: the monthly fee notice and custom
 * messages. Groups belong to one campus's classes, hence `requireSchoolContext()`.
 */
export default async function WhatsAppPage() {
  const { user } = await requireSchoolContext();
  if (!hasPermission(user, PERMISSIONS.whatsappRead)) redirect("/dashboard");

  return (
    <WhatsAppView
      canSend={hasPermission(user, PERMISSIONS.whatsappSend)}
      canManage={hasPermission(user, PERMISSIONS.whatsappManage)}
    />
  );
}
