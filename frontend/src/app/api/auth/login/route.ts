import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/api/config";
import { readTokens, setSession } from "@/lib/auth/session";

/**
 * Tenant login. One of the few handlers that touches a raw token.
 *
 * Calls the backend with `X-Token-Transport: body`, reads the pair out of the
 * response HEADERS, and stores it in this app's own httpOnly cookies. The body
 * forwarded to the browser is the backend's `LoginResponse` — which carries no
 * token fields at all, by design. The browser learns who it is and which contexts it
 * may act in, never how to prove it.
 *
 * =============================================================================
 * A 200 DOES NOT ALWAYS MEAN "SIGNED IN"
 * =============================================================================
 *   A user with several memberships — a teacher at two schools — gets
 *   `select_required: true` and NO tokens. That is not an error: they have not done
 *   anything wrong, they simply have not said which hat they are wearing, and the
 *   system must not guess. Guessing would drop them into the wrong school's data.
 *
 *   The client then calls `/api/auth/context` with a membership id, which is what
 *   actually mints the session.
 */

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const body = await request.text();

  const upstream = await fetch(backendUrl("/auth/login"), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-token-transport": "body",
      // Forwarded so the backend's audit rows see the real client rather than the
      // Next.js server. It is attacker-controllable, which is exactly why the
      // backend records it and never authorises on it.
      "x-forwarded-for": request.headers.get("x-forwarded-for") ?? "",
      "user-agent": request.headers.get("user-agent") ?? "",
    },
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
