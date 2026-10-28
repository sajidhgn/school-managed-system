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
 * The parent portal's half of `/api/auth/recover`: same loop, same fix.
 *
 * `requireGuardian()` cannot write cookies, so a portal page whose access token has
 * expired comes here. A good refresh token puts the parent back where they were;
 * otherwise the cookies are cleared and they go to the sign-in page, which
 * middleware will then leave alone.
 */

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const requested = safePath(request.nextUrl.searchParams.get("next"));
  const next = requested && requested.startsWith("/parent") ? requested : "/parent";

  const alreadyTried = await isRecovering("guardian");
  const tokens = alreadyTried ? null : await refreshSession("guardian");

  if (tokens) {
    await beginRecovery("guardian");
    return NextResponse.redirect(new URL(next, request.url));
  }

  await endRecovery("guardian");
  await clearSession("guardian");
  return NextResponse.redirect(new URL("/parent/login", request.url));
}
