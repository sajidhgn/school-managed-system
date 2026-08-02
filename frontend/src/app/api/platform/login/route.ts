import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/api/config";
import { readTokens, setSession } from "@/lib/auth/session";

/**
 * Platform operator login (spec §4.3A).
 *
 * Writes to a DIFFERENT cookie pair than tenant login. See `lib/auth/session.ts`
 * for why the two sessions are kept structurally separate rather than distinguished
 * by a claim check the middleware might forget.
 *
 * There is no matching registration handler, and there never will be: operator
 * accounts are seeded by `python -m app.cli seed`, and credentials rotate through
 * the CLI. An emailed password reset for a role that can read every school's records
 * would reduce the platform's security to the security of one inbox.
 */

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const body = await request.text();

  const upstream = await fetch(backendUrl("/platform/auth/login"), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-token-transport": "body",
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
  if (tokens) await setSession(tokens, "platform");

  return new NextResponse(payload, {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}
