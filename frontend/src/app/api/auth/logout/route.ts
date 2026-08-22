import { NextRequest, NextResponse } from "next/server";

import { clearSession, fetchWithSession } from "@/lib/auth/session";

/**
 * Sign out.
 *
 * Tells the backend to revoke the session, then clears the local cookies —
 * IN THAT ORDER, and the local clear happens regardless of what the backend said.
 *
 * If revocation fails (the backend is down, the token already expired), clearing
 * locally anyway is still correct: the user asked to be signed out and must appear
 * signed out. A logout that leaves the user logged in because a network call failed
 * is the worst possible failure mode for this particular button — especially on a
 * shared machine, which is common in a staff room.
 */

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const everywhere = request.nextUrl.searchParams.get("all") === "true";

  try {
    await fetchWithSession(
      everywhere ? "/auth/logout-all" : "/auth/logout",
      { method: "POST" },
      "tenant",
      true,
    );
  } catch {
    // Deliberately swallowed — see the docstring.
  }

  await clearSession();
  return NextResponse.json({ message: "Signed out." });
}
