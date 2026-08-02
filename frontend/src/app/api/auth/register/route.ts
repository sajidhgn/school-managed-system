import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/api/config";

/**
 * Self-service signup.
 *
 * Deliberately sets NO cookies. The backend returns 201 with no tokens, because
 * login is blocked until the emailed verification link is followed — that gate is
 * what stops signup from becoming a way to send mail from our domain to arbitrary
 * addresses.
 *
 * A thin pass-through rather than a client-side `fetch` to the API, for one reason:
 * the browser must never learn the FastAPI origin. Everything crosses through the
 * Next.js server.
 */

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const body = await request.text();

  const upstream = await fetch(backendUrl("/auth/register"), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-forwarded-for": request.headers.get("x-forwarded-for") ?? "",
      "user-agent": request.headers.get("user-agent") ?? "",
    },
    body,
    cache: "no-store",
  });

  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}
