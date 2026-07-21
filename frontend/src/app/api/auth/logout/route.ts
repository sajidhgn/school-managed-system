import { NextResponse } from "next/server";

import { backendUrl } from "@/lib/api/config";
import { clearSession, getRefreshToken } from "@/lib/auth/session";

/**
 * Sign out.
 *
 * Revokes the refresh token upstream so it cannot be replayed, then clears the
 * cookies. The cookies are cleared even if revocation fails — a user who
 * clicked "log out" must end up logged out locally regardless.
 */
export async function POST() {
  const refresh = await getRefreshToken();

  if (refresh) {
    try {
      await fetch(backendUrl("/auth/logout"), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
        cache: "no-store",
      });
    } catch {
      // Network failure to the backend must not trap the user in a session.
    }
  }

  await clearSession();
  return NextResponse.json({ detail: "Signed out." }, { status: 200 });
}
