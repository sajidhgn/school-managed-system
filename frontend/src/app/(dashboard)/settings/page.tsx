import type { Metadata } from "next";

import { requireUser } from "@/lib/auth/session";
import { SettingsView } from "./settings-view";

export const metadata: Metadata = { title: "Settings" };
export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const user = await requireUser();
  return <SettingsView user={user} />;
}
