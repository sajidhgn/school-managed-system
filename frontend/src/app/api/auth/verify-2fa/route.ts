import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/api/config";
import { setSession } from "@/lib/auth/session";
import type { TokenPair } from "@/lib/api/types";

/**
 * Complete a 2FA challenge and establish the session cookies.
 *
 * Note this endpoint returns a bare `TokenPair`, unlike `/auth/login` which
 * wraps it in a `LoginResult` — by the time a code is verified there is no
 * "requires_2fa" branch left to express.
 */
export async function POST(request: NextRequest) {
  const body = await request.json();

  const upstream = await fetch(backendUrl("/auth/login/verify-2fa"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  const payload = await upstream.json().catch(() => ({}));

  if (!upstream.ok) {
    return NextResponse.json(payload, { status: upstream.status });
  }

  const tokens = payload as TokenPair;

  if (!tokens.access_token || !tokens.refresh_token) {
    return NextResponse.json(
      { status: 502, title: "BadGateway", code: "NO_TOKENS", detail: "No tokens returned." },
      { status: 502 },
    );
  }

  await setSession(tokens);
  return NextResponse.json({ detail: "Signed in." }, { status: 200 });
}
