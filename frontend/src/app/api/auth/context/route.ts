import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/api/config";
import { getAccessToken, readTokens, setSession } from "@/lib/auth/session";

/**
 * Switch the active membership (spec §4.3E).
 *
 * Two callers, one handler:
 *   1. Straight after a login that returned `select_required` — the user has a
 *      refresh token but no scoped access token yet.
 *   2. The school/organization switcher in the app header, mid-session.
 *
 * Both re-issue the token pair scoped to the chosen membership, so both must go
 * through a handler that can write cookies. This is why context switching is on the
 * BFF's blocked list: proxying it would hand raw tokens to client JS.
 *
 * The backend verifies the membership actually belongs to the caller and returns 404
 * if not — without that check this endpoint would be a complete tenancy bypass, since
 * its entire job is to change which organization you are acting in.
 */

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const body = await request.text();
  const token = await getAccessToken();

  const headers: Record<string, string> = {
    "content-type": "application/json",
    "x-token-transport": "body",
  };
  // Present for the switcher, absent immediately after a multi-membership login.
  // The backend tolerates both: `/auth/context` is deliberately reachable with a
  // token carrying no active membership, because that is the only state it can move
  // a user out of.
  if (token) headers.authorization = `Bearer ${token}`;

  const upstream = await fetch(backendUrl("/auth/context"), {
    method: "POST",
    headers,
    body,
    cache: "no-store",
  });

  const payload = await upstream.text();

  if (!upstream.ok) {
    return new NextResponse(payload, {
      status: upstream.status,
      headers: { "content-type": "application/json" },
    });
  }

  const tokens = readTokens(upstream);
  if (tokens) await setSession(tokens);

  return new NextResponse(payload, {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}
