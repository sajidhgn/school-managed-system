import { NextResponse } from "next/server";

import { clearSession, fetchWithSession } from "@/lib/auth/session";

/**
 * Sign out of the parent portal. Clears ONLY the guardian cookies, so a teacher who
 * is also a parent stays signed in to the school panel.
 */

export const dynamic = "force-dynamic";

export async function POST() {
  try {
    await fetchWithSession("/guardian/auth/logout", { method: "POST" }, "guardian", true);
  } catch {
    // Local sign-out still wins if the API is unavailable or already expired.
  }
  await clearSession("guardian");
  return NextResponse.json({ message: "Signed out." });
}
