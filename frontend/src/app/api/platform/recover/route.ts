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
 * The platform console's half of `/api/auth/recover`.
 *
 * Same loop, same fix, separate route: middleware bounces a request holding a
 * platform cookie away from /platform/login, and `requirePlatformAdmin()` bounces an
 * unresolvable one towards it.
 *
 * Kept as its own handler rather than a `?kind=` parameter on the tenant route, for
 * the reason the BFF proxy gives: which session a request acts on is decided by the
 * path, never by something the caller can set. An operator is often signed into both
 * surfaces at once, and recovering the wrong one would sign them out of the other.
 */

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const requested = safePath(request.nextUrl.searchParams.get("next"));
  const next =
    requested && requested.startsWith("/platform") ? requested : "/platform";

  const alreadyTried = await isRecovering("platform");
  const tokens = alreadyTried ? null : await refreshSession("platform");

  if (tokens) {
    await beginRecovery("platform");
    return NextResponse.redirect(new URL(next, request.url));
  }

  await endRecovery("platform");
  await clearSession("platform");

  const login = new URL("/platform/login", request.url);
  if (next !== "/platform") login.searchParams.set("next", next);
  return NextResponse.redirect(login);
}
