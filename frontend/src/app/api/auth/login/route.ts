import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/api/config";
import { setSession } from "@/lib/auth/session";
import type { LoginResult } from "@/lib/api/types";

/**
 * Sign in.
 *
 * Forwards credentials to FastAPI, and — critically — keeps the returned token
 * pair server-side by writing it to httpOnly cookies. The browser only learns
 * whether login succeeded and whether 2FA is still required.
 */
export async function POST(request: NextRequest) {
  const body = await request.json();

  const upstream = await fetch(backendUrl("/auth/login"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  const payload = await upstream.json().catch(() => ({}));

  if (!upstream.ok) {
    return NextResponse.json(payload, { status: upstream.status });
  }

  const result = payload as LoginResult;

  // 2FA challenge: no tokens issued yet, the client must post a code next.
  if (result.requires_2fa || !result.tokens) {
    return NextResponse.json(
      { requires_2fa: true, detail: result.detail },
      { status: 200 },
    );
  }

  await setSession(result.tokens);
  return NextResponse.json({ requires_2fa: false, detail: result.detail }, { status: 200 });
}
