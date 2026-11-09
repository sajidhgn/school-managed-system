import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { whatsappMessages } from "@/lib/i18n/modules/whatsapp";
import { getCatalog } from "@/lib/i18n/server";
import { WhatsAppView } from "./whatsapp-view";

export async function generateMetadata(): Promise<Metadata> {
  const m = await getCatalog(whatsappMessages);
  return { title: m.meta.title };
}

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
