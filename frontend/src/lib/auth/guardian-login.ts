import "server-only";

import { NextResponse } from "next/server";

import type { GuardianLoginResponse } from "@/lib/api/types";
import { setAccessToken, setSession } from "@/lib/auth/session";

/**
 * Turn a backend parent-login response into this app's cookies.
 *
 * The guardian endpoints return tokens in the JSON BODY under `X-Token-Transport:
 * body` (the staff ones use headers). So the body is read here, the tokens go into
 * httpOnly cookies, and the body is forwarded with `tokens` removed: the browser
 * learns whether it is signed in and which school groups it may open, never the
 * credential itself.
 *
 *   * `authenticated`   -- a full pair: the portal session.
 *   * `select_required` -- a five-minute continuation that can only choose a school
 *                          group. Access cookie only; no refresh cookie exists yet.
 *   * `no_access`       -- the number is real but no school shows it any child.
 */
export async function relayGuardianLogin(upstream: Response): Promise<NextResponse> {
  const text = await upstream.text();

  if (!upstream.ok) {
    const headers = new Headers({
      "content-type": upstream.headers.get("content-type") ?? "application/json",
    });
    for (const name of ["x-request-id", "retry-after"]) {
      const value = upstream.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new NextResponse(text, { status: upstream.status, headers });
  }

  const body = JSON.parse(text) as GuardianLoginResponse;
  const tokens = body.tokens;

  if (body.status === "authenticated" && tokens?.refresh_token) {
    await setSession(
      { accessToken: tokens.access_token, refreshToken: tokens.refresh_token },
      "guardian",
    );
  } else if (body.status === "select_required" && tokens) {
    await setAccessToken(tokens.access_token, "guardian");
  }

  return NextResponse.json({ ...body, tokens: null } satisfies GuardianLoginResponse);
}

/** Forwarded so the backend's rate limits and audit rows see the real client. */
export function clientHeaders(request: Request): Record<string, string> {
  return {
    "x-forwarded-for": request.headers.get("x-forwarded-for") ?? "",
    "user-agent": request.headers.get("user-agent") ?? "",
  };
}
