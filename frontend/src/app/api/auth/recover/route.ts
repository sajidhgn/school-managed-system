import { NextRequest, NextResponse } from "next/server";

import {
  beginRecovery,
  clearSession,
  endRecovery,
  isRecovering,
  refreshSession,
  safePath,
} from "@/lib/auth/session";

/**
 * Where a Server Component sends a caller whose session did not resolve.
 *
 * =============================================================================
 * THIS EXISTS BECAUSE A SERVER COMPONENT CANNOT WRITE COOKIES
 * =============================================================================
 *   `requireUser()` runs during render, where Next 15 forbids cookie mutation. So
 *   it can neither refresh a session nor clear a dead one — it can only redirect,
 *   and redirecting to /login while the stale cookie is still set makes middleware
 *   bounce the user straight back. That is the 307 loop this route removes.
 *
 *   A route handler has none of those restrictions, so the decision is made here:
 *
 *     refresh works  -> put them back where they were, session intact
 *     refresh fails  -> clear the cookies, THEN go to /login, which middleware now
 *                       leaves alone because there is no session cookie to see
 *
 *   The common case is the first one. `getCurrentUser()` does not refresh, so any
 *   session idle past the access token's lifetime arrives here with a perfectly
 *   good refresh token; before this route that logged people out (or looped).
 *
 * WHY THE RECOVERY COOKIE
 *   If a refresh succeeds but the page still cannot resolve a user — a deleted
 *   account, a revoked membership, a backend that rotates tokens happily but
 *   answers `/auth/me` with a 401 — the page would bounce back here and we would
 *   loop through a working refresh instead. The marker means "already tried once":
 *   on the second pass we stop and sign out. It expires on its own in seconds, so a
 *   successful recovery leaves nothing behind.
 */

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const next = safePath(request.nextUrl.searchParams.get("next")) ?? "/dashboard";

  const alreadyTried = await isRecovering();
  const tokens = alreadyTried ? null : await refreshSession("tenant");

  if (tokens) {
    await beginRecovery();
    return NextResponse.redirect(new URL(next, request.url));
  }

  await endRecovery();
  // `refreshSession` clears on a failed rotation, but not when there was no refresh
  // token to present. Clearing unconditionally is what guarantees middleware sees a
  // clean request — the whole point of routing through here.
  await clearSession();

  const login = new URL("/login", request.url);
  if (next !== "/dashboard") login.searchParams.set("next", next);
  return NextResponse.redirect(login);
}
