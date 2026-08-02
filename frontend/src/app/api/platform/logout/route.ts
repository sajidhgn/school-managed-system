import { NextResponse } from "next/server";

import { clearSession } from "@/lib/auth/session";

/**
 * Sign out of the platform console.
 *
 * Clears ONLY the platform cookies. An operator signed into both surfaces — common
 * while debugging a customer issue — keeps their tenant session, because "leave the
 * admin console" and "log out of my school" are different intentions and conflating
 * them is a surprise nobody asked for.
 */

export const dynamic = "force-dynamic";

export async function POST() {
  await clearSession("platform");
  return NextResponse.json({ message: "Signed out of the platform console." });
}
